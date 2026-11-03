import copy, json, sys
sys.path.insert(0, '/home/user/plato')
import main_legacy as core
def spec(strategy, **over):
    x = copy.deepcopy(core.DEFAULT_INPUTS); t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns","total_area","useful","saleable","transfer","units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS: x[key] = 0
    x.update(project_kind=core.PROJECT_KIND_NONRESIDENTIAL, offices_enabled=True,
             offices_gba_sqm=22842, offices_saleable_sqm=15030,
             offices_parking_under_spaces=68, purchase_price_mln=5, land_buyout_mln=675,
             offices_strategy=strategy)
    x.update(over)
    t.setdefault("offices", {}).update(gns=22842, total_area=21472, useful=15030, saleable=15030)
    return x, t
def run(strategy, **over):
    x, t = spec(strategy, **over)
    return core._run_authoritative_model(x, t, [], {})["consolidated"]
if __name__ == "__main__":
    out = {}
    for s in ("ddu","direct","income"):
        r = run(s); sm = r["summary"]
        objs = r["finance"].get("nonres", {}).get("objects", [])
        out[s] = {k: sm.get(k) for k in ("revenue","revenue_total","capex","capex_total","net_profit","npv","irr","irr_equity","npv_equity","llcr","equity_peak","margin","margin_pct","roi")}
        out[s]["obj_totals"] = objs[0]["totals"] if objs else None
        out[s]["summary_keys"] = sorted(sm.keys())
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)

def capex_lines(r):
    for k in ("capex_breakdown","cost_items","capex_items"):
        if k in r: return k, r[k]
    rep = r.get("report") or {}
    return "keys", sorted(r.keys()), sorted(rep.keys()) if isinstance(rep, dict) else None
