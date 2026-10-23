import sys, json
sys.path.insert(0, '/tmp/claude-0/-home-user-plato/c936f76f-bdf5-5950-84e0-841f7b792428/scratchpad')
from collect import pick
def solve(s, key, lo, hi, metric="npv"):
    for _ in range(22):
        mid = (lo+hi)/2
        (lo, hi) = (lo, mid) if pick(s, **{key: mid})[metric] > 0 else (mid, hi)
    return (lo+hi)/2
r = dict(sale_price_be=solve("direct", "offices_price_th_per_sqm", 200, 800),
         rent_be=solve("income", "offices_rent_th_per_sqm_month", 1.0, 10.0),
         free_land_direct=pick("direct", land_buyout_mln=0, purchase_price_mln=0)["npv"],
         free_land_income=pick("income", land_buyout_mln=0, purchase_price_mln=0)["npv"])
inc = pick("income")
r["years"] = inc["years"]
json.dump(r, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)
print({k: v for k, v in r.items() if k != "years"})
for y in inc["years"]: print({k: (round(v/1e6,1) if isinstance(v, float) and abs(v) > 1e3 else v) for k, v in y.items()})
