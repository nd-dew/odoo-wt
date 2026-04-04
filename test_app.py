import pytest
from odoo_wt import OdooWtApp, load_config

@pytest.mark.asyncio
async def test_app_starts():
    app = OdooWtApp(load_config(), ['master'], ['pian'], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one('.title')
        print('\n🚀 UI MOUNT SUCCESSFUL: No TypeErrors!')
