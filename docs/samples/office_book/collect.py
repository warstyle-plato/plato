import sys, json
sys.path.insert(0, '/tmp/claude-0/-home-user-plato/c936f76f-bdf5-5950-84e0-841f7b792428/scratchpad')
import run_office as ro
BASE = dict(offices_price_th_per_sqm=273, offices_cost_th_per_sqm=110,
            offices_rent_th_per_sqm_month=2.5, offices_exit_cap_pct=10.5,
            offices_leaseup_months=18)
def pick(s, **over):
    p = dict(BASE); p.update(over)
    r = ro.run(s, **p); sm = r["summary"]; o = r["finance"]["nonres"]["objects"][0]
    res, k, t, fin = o["result"], o["kpi"], o["totals"], o["financing"]
    return dict(revenue=sm["revenue"], capex=sm["capex"], net=sm["net_profit"],
        npv=sm["npv"], irr=sm.get("irr_project"), irr_eq=sm.get("irr_equity"), npv_eq=sm.get("npv_equity"),
        fin_cost=sm.get("financing_cost"), tax=sm.get("profit_tax"), ebitda=sm.get("ebitda"),
        equity=sm.get("equity_contributed"), margin=sm.get("margin"),
        cost_total=res["cost_total"], obj_capex=res["capex"], equity_peak=res["equity_peak"],
        obj_npv=res["npv"], obj_irr=res["irr"], obj_profit=res["profit_after_tax"], payback=res["payback_reason"],
        noi_stab=k.get("stabilized_noi"), noi_fwd=k.get("forward_noi"), exit_value=k.get("exit_value"),
        dscr=k.get("dscr_min"), icr=k.get("icr_min"), exit_month=k.get("exit_month"),
        rent_rev=t["rent_revenue"], sale_rev=t["sale_revenue"], exit_rev=t["exit_revenue"], opex=t["opex"],
        prop_tax=t["property_tax"], selling=t["selling_cost"], loan_interest=t["loan_interest"], loan_peak=t["loan_peak"],
        rate=fin.get("avg_rate"), commissioning=fin.get("commissioning"),
        years=o["years"])
def breakeven(s, key="npv"):
    lo, hi = -6000.0, 3000.0
    f = lambda b: pick(s, land_buyout_mln=b)[key]
    if f(lo) < 0: return None
    for _ in range(18):
        mid = (lo+hi)/2
        (lo, hi) = (mid, hi) if f(mid) > 0 else (lo, mid)
    return lo + 5  # + участок 5 млн
def main():
  if True:
    out = {}
    for s in ("direct", "income"):
      out[s] = pick(s)
      out[s]["breakeven_entry"] = breakeven(s)
      sens = {}
      for name, a, b in [("price", dict(offices_price_th_per_sqm=273*0.9), dict(offices_price_th_per_sqm=273*1.1)),
                         ("rent", dict(offices_rent_th_per_sqm_month=2.25), dict(offices_rent_th_per_sqm_month=2.75)),
                         ("occ", dict(offices_occupancy_stable_pct=87), dict(offices_occupancy_stable_pct=97)),
                         ("cap", dict(offices_exit_cap_pct=11.5), dict(offices_exit_cap_pct=9.5)),
                         ("cost", dict(offices_cost_th_per_sqm=121), dict(offices_cost_th_per_sqm=99)),
                         ("entry", dict(land_buyout_mln=675+68), dict(land_buyout_mln=675-68))]:
          lo_, hi_ = pick(s, **a), pick(s, **b)
          sens[name] = dict(lo=(lo_["npv"], lo_["irr"], lo_["net"]), hi=(hi_["npv"], hi_["irr"], hi_["net"]))
      out[s]["sens"] = sens
  json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)

if __name__ == '__main__':
    main()