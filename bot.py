import asyncio
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright

URL = os.getenv('DASHBOARD_URL') or 'https://6wb7yh4qsg6n.com/login#/operations/workOrder'
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
    status_form = page.locator('.ant-form-item').filter(
        has=page.get_by_text('Status', exact=True)
    )
    control = status_form.locator('.ant-select').first
    if await control.count() == 0:
        raise RuntimeError('Could not find the Status filter on Work Order List')
    await control.click()
    option = page.locator('.ant-select-item-option-content').get_by_text(status, exact=True)
    if await option.count() == 0:
        option = page.get_by_text(status, exact=True).last
    await option.click()
    await page.get_by_role('button', name=re.compile('^Search$', re.I)).click()
    await page.wait_for_timeout(1400)


async def read_total_items(page, status):
    body = await page.locator('body').inner_text()
    match = re.search('Total +([0-9,]+) +items', body, re.I)
    if match:
        return int(match.group(1).replace(',', ''))
    raise RuntimeError('Could not read Total items for status ' + status + '. Page text: ' + body[-1200:])


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
                visible_inputs = page.locator('input:visible')
                if await visible_inputs.count() >= 3:
                    totp_secret = secret('DASHBOARD_TOTP_SECRET').replace(' ', '')
                    import pyotp
                    await visible_inputs.nth(2).fill(pyotp.TOTP(totp_secret).now())
                button = page.get_by_role('button', name=re.compile('login|sign in|登录', re.I))
                if await button.count():
                    await button.first.click()
                else:
                    await password.first.press('Enter')
                await page.wait_for_timeout(6000)
                if await password.count():
                    raise RuntimeError('Dashboard login failed; check dashboard username, password, and TOTP setup key')

            # Keep the authenticated single-page app alive; reloading the login URL can discard its in-memory session.
            table = page.locator('.ant-table').first
            try:
                await table.wait_for(state='visible', timeout=45000)
            except Exception as exc:
                body = await page.locator('body').inner_text()
                raise RuntimeError(f'Work Order List did not load. URL={page.url}; page text: {body[-1200:]}') from exc

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
