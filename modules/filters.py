from pyrogram import filters

from modules.FMS import fms


def data_filter(data):
    async def func(flt, _, query):
        return getattr(query, "data", None) == flt.data

    return filters.create(func, data=data)


def data_filter_startswith(data):
    async def func(flt, _, query):
        query_data = getattr(query, "data", None)
        return bool(query_data and query_data.startswith(flt.data))

    return filters.create(func, data=data)

def state_filter(state):
    async def func(flt, _, event):
        if not getattr(event, "from_user", None):
            return False
        st = fms.get_state(event.from_user.id)
        return flt.state == st

    return filters.create(func, state=state)


