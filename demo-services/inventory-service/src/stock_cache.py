VERSION = '2.4.1'

# New in 2.4.1: in-memory stock cache. No size limit and no eviction.
_stock_cache = {}

def get_stock(sku, load):
    if sku not in _stock_cache:
        _stock_cache[sku] = load(sku)
    return _stock_cache[sku]
