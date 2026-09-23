from auction_search.krt_cadastral_selector import classify, select

KRT = [[[0,0],[100,0],[100,100],[0,100]]]

def box(x1,y1,x2,y2):
    return [[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]]

def test_geometry_selects_object_inside_and_rejects_outside():
    inside = classify({"cadastral_number":"77:1:1:1","rings_merc":box(10,10,20,20)}, KRT)
    outside = classify({"cadastral_number":"77:1:1:2","rings_merc":box(120,120,130,130)}, KRT)
    assert inside["krt_state"] == "inside"
    assert outside["krt_state"] == "outside"

def test_related_verified_land_can_include_object_without_geometry():
    land={"cadastral_number":"77:1:1:10","rings_merc":box(5,5,40,40)}
    obj={"cadastral_number":"77:1:1:20","lands":["77:1:1:10"],"cadastral_value_rub":100}
    got=select(krt_rings=KRT,lands=[land],objects=[obj])
    assert got["inside"][0]["krt_basis"] == "related_land_inside_krt"

def test_moscow_value_is_excluded_and_private_value_is_buyout():
    land={"cadastral_number":"77:1:1:10","rings_merc":box(5,5,40,40)}
    rows=[
      {"cadastral_number":"77:1:1:20","rings_merc":box(10,10,20,20),"cadastral_value_rub":100,"owner":{"group":"moscow"}},
      {"cadastral_number":"77:1:1:21","rings_merc":box(25,25,30,30),"cadastral_value_rub":250,"owner":{"group":"other"}},
    ]
    got=select(krt_rings=KRT,lands=[land],objects=rows)
    assert got["cadastral"]["moscow_excluded_rub"] == 100
    assert got["cadastral"]["private_buyout_rub"] == 250

def test_premise_does_not_double_count_building_value():
    rows=[
      {"cadastral_number":"77:1:1:30","rings_merc":box(10,10,40,40),"kind":"building","cadastral_value_rub":1000},
      {"cadastral_number":"77:1:1:31","rings_merc":box(10,10,20,20),"kind":"premise","cadastral_value_rub":500},
    ]
    got=select(krt_rings=KRT,objects=rows)
    assert got["cadastral"]["private_buyout_rub"] == 1000


def test_land_value_is_in_private_buyout():
    land={"cadastral_number":"77:1:1:40","rings_merc":box(5,5,40,40),"kind":"land","cadastral_value_rub":700,"owner":{"group":"other","name":"ООО Собственник"}}
    got=select(krt_rings=KRT,lands=[land],objects=[])
    assert got["cadastral"]["private_buyout_rub"] == 700
    assert got["cadastral"]["private_land_rub"] == 700

def test_unknown_owner_is_not_silently_private():
    obj={"cadastral_number":"77:1:1:50","rings_merc":box(10,10,20,20),"kind":"building","cadastral_value_rub":900,"owner":{}}
    got=select(krt_rings=KRT,objects=[obj])
    assert got["cadastral"]["private_buyout_rub"] == 0
    assert got["cadastral"]["unknown_owner_count"] == 1
    assert got["cadastral"]["complete"] is False
