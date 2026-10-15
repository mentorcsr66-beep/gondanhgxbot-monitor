import asyncio, os, re
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from playwright.async_api import async_playwright

URL = 'https://6wb7yh4qsg6n.com/login#/operations/workOrder'
TZ = ZoneInfo('Asia/Jakarta')

def secret(name):
    v = os.getenv(name)
    if not v: raise RuntimeError('Missing GitHub Secret: ' + name)
    return v

async def collect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale='en-US')
        await page.goto(URL, wait_until='domcontentloaded', timeout=90000)
        password = page.locator('input[type=password]')
        if await password.count():
            users = page.locator('input:not([type=password]):visible')
            if not await users.count(): raise RuntimeError('Login field was not found')
            await users.first.fill(secret('DASHBOARD_USERNAME'))
            await password.first.fill(secret('DASHBOARD_PASSWORD'))
            login = page.get_by_role('button', name=re.compile('login|sign in|登录', re.I))
            if await login.count(): await login.first.click()
            else: await password.first.press('Enter')
            await page.wait_for_timeout(5000)
            if await password.count(): raise RuntimeError('Dashboard login failed')
        await page.goto(URL, wait_until='domcontentloaded', timeout=90000)
        await page.get_by_text('Work Order List', exact=True).click()
        await page.wait_for_timeout(1500)
        totals = {}
        for status in ('Processing', 'Pending', 'Completed'):
            # Select the status filter and refresh the list.
            control = page.get_by_text(re.compile('^Processing$|^Pending$|^Completed$')).first
            await control.click()
            await page.get_by_text(status, exact=True).last.click()
            await page.get_by_role('button', name=re.compile('^Search$', re.I)).click()
            await page.wait_for_timeout(1300)
            body = await page.locator('body').inner_text()
            match = re.search(r'Total\s+(\d+)\s+items', body, re.I)
            totals[status] = int(match.group(1)) if match else 0
        await browser.close()
    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M WIB')
    return (f'Work Order hari ini\nProcessing: {totals["Processing"]}\n'
            f'Pending: {totals["Pending"]}\nTotal completed: {totals["Completed"]}\nUpdate: {now}')

async def main():
    message = await collect()
    token, chat = secret('TELEGRAM_BOT_TOKEN'), secret('TELEGRAM_CHAT_ID')
    response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat, 'text': message}, timeout=30)
    response.raise_for_status()
    if not response.json().get('ok'): raise RuntimeError('Telegram sendMessage failed')

if __name__ == '__main__': asyncio.run(main())
