import asyncio
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright

URL = os.getenv('DASHBOARD_URL', 'https://6wb7yh4qsg6n.com/login#/operations/workOrder')
TZ = ZoneInfo('Asia/Jakarta')
STATUSES = ('Processing', 'Pending', 'Completed')


def secret(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError('Missing GitHub Secret: ' + name)
    return value


def reply_to_start():
    token = secret('TELEGRAM_BOT_TOKEN')
    api = f'https://api.telegram.org/bot{token}'
    response = requests.get(api + '/getUpdates', params={'timeout': 0}, timeout=20)
    response.raise_for_status()
    updates = response.json().get('result', [])
    for update in updates:
        message = update.get('message', {})
        user = message.get('from', {})
        if message.get('text', '').startswith('/start') and user.get('username', '').lower() == 'yongwan88':
            requests.post(api + '/sendMessage', json={
                'chat_id': message['chat']['id'],
                'text': 'Bot aktif. Laporan status Work Order dikirim setiap 5 menit.'
            }, timeout=20).raise_for_status()
    if updates:
        requests.get(api + '/getUpdates', params={
            'offset': max(item['update_id'] for item in updates) + 1,
            'timeout': 0
        }, timeout=20).raise_for_status()


async def select_status(page, status):
    # Target the Status filter in the Work Order List search form.
    status_form = page.locator('.ant-form-item').filter(
        has=page.get_by_text('Status', exact=True)
    )
    control = status_form.locator('.ant-select').first
    if await control.count() == 0:
        # Fallback for dashboard builds that use a different component library.
        control = page.get_by_text(re.compile(r'^(Processing|Pending|Completed)$')).first
    await control.click()
    option = page.locator('.ant-select-item-option-content').get_by_text(status, exact=True)
    if await option.count() == 0:
        option = page.get_by_text(status, exact=True).last
    await option.click()
    await page.get_by_role('button', name=re.compile(r'^Search$', re.I)).click()
    await page.wait_for_timeout(1400)


async def read_total_items(page, status):
    body = await page.locator('body').inner_text()
    match = re.search(r'Total\s+([\d,]+)\s+items', body, re.I)
    if match:
        return int(match.group(1).replace(',', ''))
    # A clear failure helps identify localization or page-load changes in Actions logs.
    raise RuntimeError('Could not read the Total items count for status: ' + status)


async def collect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(locale='en-US')
            await page.goto(URL, wait_until='domcontentloaded', timeout=90000)
            password = page.locator('input[type=password]')
            if await password.count():
                users = page.locator('input:not([type=password]):visible')
                if not await users.count():
                    raise RuntimeError('Dashboard login field was not found')
                await users.first.fill(secret('DASHBOARD_USERNAME'))
                await password.first.fill(secret('DASHBOARD_PASSWORD'))
                button = page.get_by_role('button', name=re.compile('login|sign in|登录', re.I))
                if await button.count():
                    await button.first.click()
                else:
                    await password.first.press('Enter')
                await page.wait_for_timeout(5000)
                if await password.count():
                    raise RuntimeError('Dashboard login failed; check dashboard credentials')

            # The supplied URL opens Operations > Work Order > Work Order List directly.
            # Do not click the tab label: the site decorates/localizes that label.
            await page.goto(URL, wait_until='domcontentloaded', timeout=90000)
            await page.locator('table').first.wait_for(state='visible', timeout=30000)
            totals = {}
            for status in STATUSES:
                await select_status(page, status)
                totals[status] = await read_total_items(page, status)
        finally:
            await browser.close()

    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M WIB')
    return chr(10).join((
        '📊 Work Order List',
        f'Processing: {totals["Processing"]}',
        f'Pending: {totals["Pending"]}',
        f'Completed: {totals["Completed"]}',
        f'Update: {now}',
    ))


async def main():
    reply_to_start()
    report = await collect()
    token = secret('TELEGRAM_BOT_TOKEN')
    chat_id = secret('TELEGRAM_CHAT_ID')
    response = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id, 'text': report}, timeout=30)
    response.raise_for_status()
    if not response.json().get('ok'):
        raise RuntimeError('Telegram sendMessage failed')


if __name__ == '__main__':
    asyncio.run(main())
