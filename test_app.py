import pytest
from odoo_wt import OdooWtApp, WizardApp, load_config

@pytest.mark.asyncio
async def test_app_starts():
    app = OdooWtApp(load_config(), ['master'], ['pian'], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one('.title')
        print('\n🚀 MAIN APP MOUNT SUCCESSFUL!')

@pytest.mark.asyncio
async def test_wizard_starts():
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one('.title')
        print('\n🚀 WIZARD MOUNT SUCCESSFUL!')
