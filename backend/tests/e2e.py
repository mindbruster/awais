"""
End-to-end smoke test of every implemented feature.
Assumes: Postgres up, migrations + seed run, uvicorn on 127.0.0.1:8000.

Run: python -m tests.e2e
"""
from __future__ import annotations

import io
import sys
from datetime import date
from decimal import Decimal

import httpx

BASE = "http://127.0.0.1:8000"
API = f"{BASE}/api/v1"

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name, detail))
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"{tag} {name}" + (f"  -- {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    client = httpx.Client(base_url=API, timeout=30)

    # ----- AUTH -----
    section("Auth")
    r = client.post("/auth/login", json={"email": "admin@jewelryerp.com", "password": "admin123"})
    check("admin login → 200", r.status_code == 200, str(r.status_code))
    token = r.json().get("access_token")
    check("login returns token", bool(token))
    auth = {"Authorization": f"Bearer {token}"}

    r = client.post("/auth/login", json={"email": "admin@jewelryerp.com", "password": "wrong"})
    check("bad password → 401", r.status_code == 401)

    r = client.get("/auth/me")
    check("/me without token → 401", r.status_code == 401)

    r = client.get("/auth/me", headers=auth)
    check("/me with token → 200", r.status_code == 200)
    me = r.json()
    check("me has admin role", me["role"]["name"] == "admin")

    # ----- USERS (admin-only) -----
    section("Users")
    r = client.get("/users", headers=auth)
    check("admin can list users", r.status_code == 200 and len(r.json()) >= 1)

    r = client.post(
        "/users",
        headers=auth,
        json={
            "email": "staff1@jewelry.local",
            "full_name": "Staff One",
            "password": "staff123",
            "role_id": next(role["id"] for role in [r.json()[0]["role"]] if role["name"] == "admin") + 2,  # crude; we'll fix
        },
    )
    # Actually, look up role_id properly:
    # Re-list roles via a user record's role; simpler: hit /auth/me which gave admin role id
    admin_role_id = me["role"]["id"]
    # We seeded 3 roles; staff is admin_role_id + 2 (insertion order)
    staff_role_id = admin_role_id + 2

    # Re-create with correct id
    r = client.post(
        "/users",
        headers=auth,
        json={
            "email": "staff_e2e@jewelryerp.com",
            "full_name": "Staff E2E",
            "password": "staff123",
            "role_id": staff_role_id,
        },
    )
    check("admin creates staff user → 201", r.status_code == 201, str(r.status_code))
    staff_id = r.json().get("id")

    # Duplicate email
    r = client.post(
        "/users",
        headers=auth,
        json={
            "email": "staff_e2e@jewelryerp.com",
            "full_name": "dup",
            "password": "x123456",
            "role_id": staff_role_id,
        },
    )
    check("duplicate email → 409", r.status_code == 409)

    # Staff token, then verify staff cannot list users
    r = client.post("/auth/login", json={"email": "staff_e2e@jewelryerp.com", "password": "staff123"})
    check("staff login → 200", r.status_code == 200)
    staff_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/users", headers=staff_auth)
    check("staff cannot list users → 403", r.status_code == 403)

    # ----- CUSTOMERS -----
    section("Customers")
    r = client.post(
        "/customers",
        headers=auth,
        json={"name": "Acme Jewels", "phone": "555-1234", "email": "acme@example.com"},
    )
    check("create customer → 201", r.status_code == 201)
    customer_id = r.json()["id"]

    r = client.get("/customers", headers=auth, params={"q": "Acme"})
    check("search customer", r.status_code == 200 and len(r.json()) >= 1)

    r = client.patch(f"/customers/{customer_id}", headers=auth, json={"phone": "555-9999"})
    check("patch customer", r.status_code == 200 and r.json()["phone"] == "555-9999")

    # ----- VENDORS -----
    section("Vendors")
    karigar = client.post(
        "/vendors", headers=auth, json={"name": "Ravi Karigar", "type": "karigar"}
    ).json()
    fixer = client.post(
        "/vendors", headers=auth, json={"name": "Stone Master", "type": "stone_fixer"}
    ).json()
    polisher = client.post(
        "/vendors", headers=auth, json={"name": "Glow Polish", "type": "polish"}
    ).json()
    check("create karigar / fixer / polisher", all(v.get("id") for v in (karigar, fixer, polisher)))

    r = client.get("/vendors", headers=auth, params={"type": "karigar"})
    check("filter vendors by type", r.status_code == 200 and all(v["type"] == "karigar" for v in r.json()))

    # ----- INVENTORY (raw) -----
    section("Inventory (raw)")
    raw_gold = client.post(
        "/inventory",
        headers=auth,
        json={"type": "raw_gold", "label": "22k bullion", "weight_g": "500", "purity": 22, "location": "vault"},
    ).json()
    raw_stones = client.post(
        "/inventory",
        headers=auth,
        json={"type": "raw_stone", "label": "diamonds VS1", "weight_ct": "20"},
    ).json()
    check("raw gold created (500g)", Decimal(str(raw_gold["weight_g"])) == Decimal("500"))
    check("raw stones created (20ct)", Decimal(str(raw_stones["weight_ct"])) == Decimal("20"))

    # ----- PRODUCTS (auto-serial + image) -----
    section("Products")
    r = client.post(
        "/products",
        headers=auth,
        json={"name": "Test Ring (auto serial)", "gold_weight_g": "5", "gold_purity": 22},
    )
    check("auto-serial product created", r.status_code == 201)
    p1 = r.json()
    check("serial follows P-YY-NNNNN", p1["serial_no"].startswith("P-26-"), p1["serial_no"])

    r = client.post(
        "/products",
        headers=auth,
        json={"serial_no": p1["serial_no"], "name": "dup"},
    )
    check("duplicate serial → 409", r.status_code == 409)

    # Image upload
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    r = client.post(
        f"/products/{p1['id']}/image",
        headers=auth,
        files={"file": ("test.png", io.BytesIO(fake_png), "image/png")},
    )
    check("image upload accepted", r.status_code == 200, str(r.status_code))
    check("image_url set on product", (r.json().get("image_url") or "").startswith("/static/"))

    r = client.post(
        f"/products/{p1['id']}/image",
        headers=auth,
        files={"file": ("bad.exe", io.BytesIO(b"x"), "application/octet-stream")},
    )
    check("disallowed extension → 415", r.status_code == 415)

    # ----- STOCK MOVEMENT (direct adjustment) -----
    section("Stock movements (direct)")
    # Direct stock adjustments now require password confirmation (Phase 8 alignment).
    pwd_h = {**auth, "X-Confirm-Password": "admin123"}
    # No password → 401
    r = client.post(
        "/stock-movements",
        headers=auth,
        json={"inventory_item_id": raw_gold["id"], "type": "adjustment", "weight_g_delta": "-1"},
    )
    check("stock movement without password → 401", r.status_code == 401)

    r = client.post(
        "/stock-movements",
        headers=pwd_h,
        json={
            "inventory_item_id": raw_gold["id"],
            "type": "adjustment",
            "weight_g_delta": "-1.5",
            "notes": "weighing correction",
        },
    )
    check("adjustment posted (with password)", r.status_code == 201, str(r.status_code))

    # Verify snapshot updated to 498.5
    r = client.get(f"/inventory/{raw_gold['id']}", headers=auth)
    check(
        "raw gold snapshot decremented",
        Decimal(str(r.json()["weight_g"])) == Decimal("498.5"),
        f"got {r.json()['weight_g']}",
    )

    # Underflow guard
    r = client.post(
        "/stock-movements",
        headers=pwd_h,
        json={"inventory_item_id": raw_gold["id"], "type": "adjustment", "weight_g_delta": "-100000"},
    )
    check("underflow rejected → 400", r.status_code == 400)

    # ----- MANUFACTURING (full flow) -----
    section("Manufacturing")
    # Open job
    r = client.post("/manufacturing", headers=auth, json={"notes": "ring batch #1"})
    check("open draft job", r.status_code == 201)
    job = r.json()
    check("job_no generated MJ-YY-NNNNN", job["job_no"].startswith("MJ-26-"), job["job_no"])

    # Wrong vendor type → 400
    r = client.post(
        f"/manufacturing/{job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": fixer["id"],  # passing stone_fixer where karigar expected
            "gold_assigned_g": "10",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("wrong vendor type rejected → 400", r.status_code == 400)

    # Correct assignment
    r = client.post(
        f"/manufacturing/{job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "10",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("assign karigar → 200", r.status_code == 200)
    check("stage now karigar_assigned", r.json()["stage"] == "karigar_assigned")

    # Inventory should drop by 10
    r = client.get(f"/inventory/{raw_gold['id']}", headers=auth)
    check(
        "raw gold dropped after karigar assignment",
        Decimal(str(r.json()["weight_g"])) == Decimal("488.5"),
        r.json()["weight_g"],
    )

    # Receive 9.7g (loss = 0.3g)
    r = client.post(
        f"/manufacturing/{job['id']}/receive-karigar",
        headers=auth,
        json={"jewelry_received_g": "9.7"},
    )
    check("receive karigar → 200", r.status_code == 200)
    check("karigar loss = 0.3g", Decimal(str(r.json()["karigar_loss_g"])) == Decimal("0.3"), r.json()["karigar_loss_g"])

    # Receive more than assigned → 400
    r = client.post(
        f"/manufacturing/{job['id']}/receive-karigar",
        headers=auth,
        json={"jewelry_received_g": "20"},
    )
    check(
        "extra receive rejected (wrong stage anyway → 409)",
        r.status_code in (400, 409),
        str(r.status_code),
    )

    # Assign stone fixer
    r = client.post(
        f"/manufacturing/{job['id']}/assign-stone-fixer",
        headers=auth,
        json={
            "stone_fixer_id": fixer["id"],
            "stones_assigned_ct": "2.0",
            "stone_source_inventory_id": raw_stones["id"],
        },
    )
    check("assign stone fixer → 200", r.status_code == 200)

    # Stones inventory should drop 2ct → 18
    r = client.get(f"/inventory/{raw_stones['id']}", headers=auth)
    check("raw stones dropped to 18ct", Decimal(str(r.json()["weight_ct"])) == Decimal("18"))

    # Receive: used 1.8, returned 0.2
    r = client.post(
        f"/manufacturing/{job['id']}/receive-stone-fixer",
        headers=auth,
        json={"stones_used_ct": "1.8", "stones_returned_ct": "0.2"},
    )
    check("receive stones", r.status_code == 200 and Decimal(str(r.json()["stones_used_ct"])) == Decimal("1.8"))

    # D1 — the 0.2ct handed back must return to stock. 18 + 0.2 = 18.2.
    r = client.get(f"/inventory/{raw_stones['id']}", headers=auth)
    check(
        "returned stones credited back to inventory (D1)",
        Decimal(str(r.json()["weight_ct"])) == Decimal("18.2"),
        f"got {r.json()['weight_ct']}ct, expected 18.2",
    )

    # Assign polish
    r = client.post(
        f"/manufacturing/{job['id']}/assign-polish",
        headers=auth,
        json={"polish_vendor_id": polisher["id"], "weight_before_polish_g": "9.7"},
    )
    check("assign polish", r.status_code == 200)

    # Receive polish: 9.6g (loss 0.1g)
    r = client.post(
        f"/manufacturing/{job['id']}/receive-polish",
        headers=auth,
        json={"weight_after_polish_g": "9.6"},
    )
    check("receive polish; loss 0.1g", Decimal(str(r.json()["polish_loss_g"])) == Decimal("0.1"))

    # Complete: creates Product + finished_product InventoryItem.
    # Now requires password (Phase 8 alignment).
    r = client.post(
        f"/manufacturing/{job['id']}/complete",
        headers=auth,
        json={"product_name": "Should Need Password"},
    )
    check("complete without password → 401", r.status_code == 401)

    r = client.post(
        f"/manufacturing/{job['id']}/complete",
        headers=pwd_h,
        json={
            "product_name": "Finished Test Ring",
            "category": "ring",
            "finished_inventory_location": "showroom",
        },
    )
    check("complete job → 200", r.status_code == 200)
    completed = r.json()
    check("stage = completed", completed["stage"] == "completed")
    check("product_id assigned", completed["product_id"] is not None)
    finished_product_id = completed["product_id"]

    # Verify finished inventory exists with qty 1, weight 9.6g, stones 1.8ct
    r = client.get("/inventory", headers=auth, params={"type": "finished_product"})
    finished_inv = next((it for it in r.json() if it.get("product_id") == finished_product_id), None)
    check(
        "finished-goods inventory created",
        finished_inv is not None
        and finished_inv["quantity"] == 1
        and Decimal(str(finished_inv["weight_g"])) == Decimal("9.6")
        and Decimal(str(finished_inv["weight_ct"])) == Decimal("1.8"),
        str(finished_inv),
    )

    # Check stock ledger has manufacturing entries for this job
    r = client.get("/stock-movements", headers=auth, params={"limit": 500})
    ledger = r.json()
    job_movements = [m for m in ledger if m.get("reference_type") == "manufacturing_job" and m.get("reference_id") == job["id"]]
    check(
        "ledger has 4 entries for job (gold out, stones out, stones returned, finished in)",
        len(job_movements) == 4,
        f"got {len(job_movements)}",
    )

    # ----- COSTS (Phase 7) — set on a fresh job, verify roll-up into product -----
    section("Costs (Phase 7)")
    cj = client.post("/manufacturing", headers=auth, json={"notes": "cost roll-up"}).json()
    client.post(
        f"/manufacturing/{cj['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "5",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    client.post(
        f"/manufacturing/{cj['id']}/receive-karigar",
        headers=auth,
        json={"jewelry_received_g": "4.9"},
    )
    r = client.post(
        f"/manufacturing/{cj['id']}/costs",
        headers=auth,
        json={"karigar_cost": "200", "polish_cost": "50", "other_cost": "10"},
    )
    check("set costs on job", r.status_code == 200)
    check("costs persisted", Decimal(str(r.json()["karigar_cost"])) == Decimal("200"))

    r = client.post(
        f"/manufacturing/{cj['id']}/complete",
        headers=pwd_h,
        json={"product_name": "Cost-test ring"},
    )
    check("complete cost-test job", r.status_code == 200)
    cost_product_id = r.json()["product_id"]
    r = client.get(f"/products/{cost_product_id}", headers=auth)
    check(
        "product.total_cost = 200 + 0 + 50 + 10 = 260",
        Decimal(str(r.json()["total_cost"])) == Decimal("260.00"),
        f"got {r.json()['total_cost']}",
    )

    # Costs locked once completed
    r = client.post(
        f"/manufacturing/{cj['id']}/costs",
        headers=auth,
        json={"karigar_cost": "999"},
    )
    check("cost edit on completed job rejected → 409", r.status_code == 409)

    # ----- SALES: NORMAL -----
    section("Sales (normal)")
    inv_payload = {
        "customer_id": customer_id,
        "sale_type": "normal",
        "gold_rate_per_g": "6500",
        "discount_amount": "100",
        "discount_weight_g": "0",
        "tax_amount": "50",
        "items": [
            {
                "product_id": finished_product_id,
                "description": "Finished Test Ring",
                "quantity": 1,
                "gold_weight_g": "9.6",
                "gold_purity": 22,
                "gold_rate_per_g": "6500",
                "stone_weight_ct": "1.8",
                "stone_rate_per_ct": "10000",
                "labor_amount": "1500",
            }
        ],
    }
    r = client.post("/invoices", headers=auth, json=inv_payload)
    check("create draft invoice → 201", r.status_code == 201, str(r.status_code))
    inv = r.json()
    check("invoice_no generated INV-YY-NNNNN", inv["invoice_no"].startswith("INV-26-"))
    check("status = draft", inv["status"] == "draft")
    # gold = 9.6 * 22/24 * 6500 = 57200 ; stone = 1.8*10000=18000 ; line = 57200+18000+1500=76700
    expected_line = Decimal("76700.00")
    line_total = Decimal(str(inv["items"][0]["line_total"]))
    check("line total math", line_total == expected_line, f"got {line_total}")
    expected_total = expected_line - Decimal("100") - Decimal("0") + Decimal("50")
    check("invoice total math", Decimal(str(inv["total"])) == expected_total)

    invoice_id = inv["id"]

    # Issue → must deduct stock. Now requires password (Phase 8 alignment).
    r = client.post(f"/invoices/{invoice_id}/issue", headers=auth)
    check("issue without password → 401", r.status_code == 401)
    r = client.post(f"/invoices/{invoice_id}/issue", headers=pwd_h)
    check("issue normal sale → 200", r.status_code == 200)
    check("status = issued", r.json()["status"] == "issued")

    # Verify finished inventory dropped to 0
    r = client.get("/inventory", headers=auth, params={"type": "finished_product"})
    f2 = next((it for it in r.json() if it.get("product_id") == finished_product_id), None)
    check("finished inventory deducted on issue", f2 and f2["quantity"] == 0)

    # Verify product status = sold
    r = client.get(f"/products/{finished_product_id}", headers=auth)
    check("product marked sold", r.json()["status"] == "sold")

    # Mark paid
    r = client.post(f"/invoices/{invoice_id}/mark-paid", headers=auth)
    check("mark paid", r.status_code == 200 and r.json()["status"] == "paid")

    # Already issued → can't re-issue (pass password so we hit the lifecycle check)
    r = client.post(f"/invoices/{invoice_id}/issue", headers=pwd_h)
    check("re-issue blocked → 409", r.status_code == 409)

    # ----- SALES: ON-APPROVAL (must NOT deduct stock) -----
    section("Sales (on-approval)")
    # Create a second finished piece via manufacturing to test approval flow
    r = client.post("/manufacturing", headers=auth, json={"notes": "ring 2"})
    j2 = r.json()
    client.post(f"/manufacturing/{j2['id']}/assign-karigar", headers=auth, json={
        "karigar_id": karigar["id"], "gold_assigned_g": "8", "gold_assigned_purity": 22,
        "gold_source_inventory_id": raw_gold["id"],
    })
    client.post(f"/manufacturing/{j2['id']}/receive-karigar", headers=auth, json={"jewelry_received_g": "7.9"})
    client.post(f"/manufacturing/{j2['id']}/complete", headers=pwd_h, json={"product_name": "Ring 2", "category": "ring"})
    r = client.get(f"/manufacturing/{j2['id']}", headers=auth)
    p2_id = r.json()["product_id"]
    r = client.get("/inventory", headers=auth, params={"type": "finished_product"})
    p2_inv = next((it for it in r.json() if it.get("product_id") == p2_id), None)
    check("ring 2 inventory has qty 1", p2_inv and p2_inv["quantity"] == 1)

    inv2 = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id,
        "sale_type": "on_approval",
        "gold_rate_per_g": "6500",
        "items": [{
            "product_id": p2_id,
            "description": "Ring 2",
            "gold_weight_g": "7.9",
            "gold_purity": 22,
            "stone_weight_ct": "0",
            "labor_amount": "0",
        }],
    }).json()

    r = client.post(f"/invoices/{inv2['id']}/issue", headers=pwd_h)
    check("issue on-approval → 200", r.status_code == 200)

    # Stock must NOT be deducted
    r = client.get("/inventory", headers=auth, params={"type": "finished_product"})
    p2_after = next((it for it in r.json() if it.get("product_id") == p2_id), None)
    check(
        "on-approval did NOT deduct stock",
        p2_after and p2_after["quantity"] == 1,
        f"qty={p2_after['quantity'] if p2_after else None}",
    )

    # Product status must flip to on_approval
    r = client.get(f"/products/{p2_id}", headers=auth)
    check("product marked on_approval", r.json()["status"] == "on_approval")

    # Void on-approval → product back to in_stock, stock untouched.
    # Void requires password confirmation header (Phase 8).
    r = client.post(
        f"/invoices/{inv2['id']}/void",
        headers={**auth, "X-Confirm-Password": "admin123"},
    )
    check("void on-approval", r.status_code == 200 and r.json()["status"] == "void")
    r = client.get(f"/products/{p2_id}", headers=auth)
    check("product status reset to in_stock after void", r.json()["status"] == "in_stock")
    r = client.get("/inventory", headers=auth, params={"type": "finished_product"})
    p2_v = next((it for it in r.json() if it.get("product_id") == p2_id), None)
    check("on-approval void leaves stock at 1", p2_v["quantity"] == 1)

    # Void the (already paid) normal invoice should be blocked (only draft/issued can void).
    # Pass the password so we exercise the lifecycle check, not the auth gate.
    r = client.post(
        f"/invoices/{invoice_id}/void",
        headers={**auth, "X-Confirm-Password": "admin123"},
    )
    check("void of paid invoice rejected → 409", r.status_code == 409, str(r.status_code))

    # ----- SERIAL UNIQUENESS UNDER LIGHT CONCURRENCY -----
    section("Serial concurrency")
    import concurrent.futures

    def mint() -> str:
        with httpx.Client(base_url=API, timeout=15) as c:
            return c.post(
                "/products",
                headers=auth,
                json={"name": "Concurrent piece", "gold_weight_g": "1"},
            ).json().get("serial_no", "")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        serials = list(ex.map(lambda _: mint(), range(8)))
    check("8 concurrent products all get a serial", all(serials))
    check("serials are unique under concurrency", len(set(serials)) == len(serials), f"got {serials}")

    # ----- REPORTS (Phase 11) -----
    section("Reports")
    r = client.get("/reports/stock", headers=auth)
    check("stock report 200", r.status_code == 200)
    sb = r.json()
    check("stock report buckets present", isinstance(sb.get("by_type"), list) and len(sb["by_type"]) >= 1)

    r = client.get("/reports/sales", headers=auth)
    check("sales report 200", r.status_code == 200)
    sales = r.json()
    check(
        "sales count >= 1",
        sales["invoice_count"] >= 1,
        f"got {sales['invoice_count']}",
    )
    # Currency rollup is present
    check(
        "sales report has by_currency rollup",
        isinstance(sales.get("by_currency"), list) and len(sales["by_currency"]) >= 1,
    )
    # Each by_sale_type bucket carries a currency
    check(
        "sales by_sale_type rows tagged with currency",
        all("currency" in b for b in sales["by_sale_type"]),
    )

    r = client.get("/reports/manufacturing-loss", headers=auth)
    check("loss report 200", r.status_code == 200)
    lr = r.json()
    check("karigar loss aggregate present", Decimal(str(lr["overall_karigar_loss_g"])) > 0)

    r = client.get("/reports/profit", headers=auth)
    check("profit report 200", r.status_code == 200)
    pr = r.json()
    # Identity per currency: revenue - cost = profit
    check(
        "profit by_currency identity holds",
        all(
            Decimal(str(b["profit"]))
            == (Decimal(str(b["revenue"])) - Decimal(str(b["making_cost"]))).quantize(Decimal("0.01"))
            for b in pr["by_currency"]
        ),
        f"by_currency={pr['by_currency']}",
    )
    check(
        "profit rows tagged with currency",
        all("currency" in r for r in pr["rows"]),
    )

    # ----- RBAC (Phase 8): staff + accountant roles -----
    section("RBAC")

    # Use the staff token already created above. Try perm-gated endpoints.
    r = client.get("/products", headers=staff_auth)
    check("staff can list products", r.status_code == 200)
    r = client.post("/invoices", headers=staff_auth, json={
        "customer_id": customer_id, "sale_type": "normal", "items": [],
    })
    check("staff cannot create invoice → 403", r.status_code == 403)
    r = client.get("/reports/profit", headers=staff_auth)
    check("staff cannot see profit report → 403", r.status_code == 403)
    r = client.get("/reports/sales", headers=staff_auth)
    check("staff cannot see sales report → 403", r.status_code == 403)
    r = client.get("/reports/stock", headers=staff_auth)
    check("staff CAN see stock report", r.status_code == 200)
    r = client.get("/reports/manufacturing-loss", headers=staff_auth)
    check("staff CAN see loss report", r.status_code == 200)

    # Create accountant
    accountant_role_id = admin_role_id + 1
    r = client.post("/users", headers=auth, json={
        "email": "acct_e2e@jewelryerp.com", "full_name": "Acct E2E",
        "password": "acct1234", "role_id": accountant_role_id,
    })
    check("admin creates accountant", r.status_code == 201)
    r = client.post("/auth/login", json={"email": "acct_e2e@jewelryerp.com", "password": "acct1234"})
    acct_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/reports/profit", headers=acct_auth)
    check("accountant CAN see profit report", r.status_code == 200)
    r = client.get("/users", headers=acct_auth)
    check("accountant cannot manage users → 403", r.status_code == 403)
    r = client.post("/products", headers=acct_auth, json={"name": "blocked"})
    check("accountant cannot create products → 403", r.status_code == 403)

    # ----- PASSWORD CONFIRMATION on sensitive actions -----
    section("Password confirmation")
    # Create a draft invoice for the void test
    di = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "items": [],
    }).json()
    # void without header → 401
    r = client.post(f"/invoices/{di['id']}/void", headers=auth)
    check("void without password → 401", r.status_code == 401)
    # wrong password → 401
    r = client.post(f"/invoices/{di['id']}/void",
                    headers={**auth, "X-Confirm-Password": "wrong"})
    check("void wrong password → 401", r.status_code == 401)
    # correct password → 200
    r = client.post(f"/invoices/{di['id']}/void",
                    headers={**auth, "X-Confirm-Password": "admin123"})
    check("void with correct password → 200", r.status_code == 200)

    # ----- EDIT (PATCH) endpoints -----
    section("Edit endpoints")
    r = client.patch(f"/customers/{customer_id}", headers=auth, json={"address": "New Address 1"})
    check("PATCH customer.address", r.status_code == 200 and r.json()["address"] == "New Address 1")
    r = client.patch(f"/vendors/{karigar['id']}", headers=auth, json={"phone": "999-1234"})
    check("PATCH vendor.phone", r.status_code == 200 and r.json()["phone"] == "999-1234")
    r = client.patch(f"/products/{p1['id']}", headers=auth, json={"category": "ring"})
    check("PATCH product.category", r.status_code == 200 and r.json()["category"] == "ring")

    # ----- CUSTOMER PURCHASE HISTORY (filter on /invoices) -----
    section("Customer history")
    r = client.get("/invoices", headers=auth, params={"customer_id": customer_id})
    check("filter invoices by customer_id", r.status_code == 200)
    rows = r.json()
    check(
        "all returned invoices belong to that customer",
        all(inv["customer_id"] == customer_id for inv in rows),
        f"got {[i['customer_id'] for i in rows]}",
    )
    check("at least one invoice for the test customer", len(rows) >= 1)

    # ----- WHATSAPP (Phase 9) -----
    section("WhatsApp")
    inv_to_send = next((i for i in rows if i.get("status") in ("issued", "paid", "draft")), None)
    if inv_to_send is None:
        check("found an invoice for whatsapp test", False, "no candidate")
    else:
        r = client.post(f"/invoices/{inv_to_send['id']}/send-whatsapp", headers=auth)
        check(
            "WhatsApp returns 503 when provider=none",
            r.status_code == 503,
            f"got {r.status_code}: {r.text[:200]}",
        )

    # Customer with no phone → 400
    nop = client.post("/customers", headers=auth, json={"name": "No Phone"}).json()
    np_inv = client.post(
        "/invoices",
        headers=auth,
        json={"customer_id": nop["id"], "sale_type": "normal", "items": []},
    ).json()
    r = client.post(f"/invoices/{np_inv['id']}/send-whatsapp", headers=auth)
    check(
        "WhatsApp returns 400 when customer has no phone",
        r.status_code == 400,
        f"got {r.status_code}",
    )

    # ----- SEARCH (q) on every list endpoint -----
    section("Search filters")
    r = client.get("/customers", headers=auth, params={"q": "Acme"})
    check("customers q=Acme returns matches", r.status_code == 200 and len(r.json()) >= 1)
    r = client.get("/vendors", headers=auth, params={"q": "Ravi"})
    check("vendors q=Ravi returns the karigar", r.status_code == 200 and len(r.json()) >= 1)
    r = client.get("/inventory", headers=auth, params={"q": "bullion"})
    check("inventory q=bullion returns the raw gold", r.status_code == 200 and len(r.json()) >= 1)
    r = client.get("/products", headers=auth, params={"q": "P-26"})
    check("products q=P-26 matches serials", r.status_code == 200 and len(r.json()) >= 1)
    r = client.get("/invoices", headers=auth, params={"q": "INV-26"})
    check("invoices q=INV-26 matches invoice_no", r.status_code == 200 and len(r.json()) >= 1)
    # nonsense search returns empty list (200, not 500)
    r = client.get("/customers", headers=auth, params={"q": "zzznomatchzzz"})
    check("customers no-match returns []", r.status_code == 200 and r.json() == [])

    # ----- DELETE flows -----
    section("Delete flows")
    # Create throwaway customer + vendor + inventory item + product to delete
    cust = client.post("/customers", headers=auth, json={"name": "ToDelete Cust"}).json()
    r = client.delete(f"/customers/{cust['id']}", headers=auth)
    check("delete customer (no FK) → 204", r.status_code == 204)

    vend = client.post("/vendors", headers=auth, json={"name": "ToDelete Vend", "type": "other"}).json()
    r = client.delete(f"/vendors/{vend['id']}", headers=auth)
    check("delete vendor → 204", r.status_code == 204)

    inv_item = client.post(
        "/inventory",
        headers=auth,
        json={"type": "other", "label": "ToDelete Inv", "weight_g": "0"},
    ).json()
    # Inventory delete now requires password (Phase 8 alignment).
    r = client.delete(f"/inventory/{inv_item['id']}", headers=auth)
    check("inventory delete without password → 401", r.status_code == 401)
    r = client.delete(f"/inventory/{inv_item['id']}", headers=pwd_h)
    check("delete inventory item (with password) → 204", r.status_code == 204)

    # Product delete requires password (Phase 8). Without header → 401.
    prod = client.post("/products", headers=auth, json={"name": "ToDelete Prod"}).json()
    r = client.delete(f"/products/{prod['id']}", headers=auth)
    check("product delete without password → 401", r.status_code == 401)
    r = client.delete(
        f"/products/{prod['id']}",
        headers={**auth, "X-Confirm-Password": "admin123"},
    )
    check("product delete with password → 204", r.status_code == 204)

    # FK protection: customer linked to invoices must NOT be deleteable
    r = client.delete(f"/customers/{customer_id}", headers=auth)
    check("delete customer with invoices rejected (FK RESTRICT)", r.status_code in (400, 409, 500))

    # ----- GOLD RATES (Phase items+stones) -----
    section("Gold rates")
    # No rate set → /current returns 404
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24})
    check("no rate yet → 404", r.status_code == 404)
    # Set a rate
    r = client.post("/gold-rates", headers=auth, json={
        "rate_date": "2026-04-29", "currency": "PKR", "rate_per_g": "6500", "purity": 24,
    })
    check("set PKR/24k rate → 201", r.status_code == 201)
    rate_id = r.json()["id"]
    # /current now finds it
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24})
    check("/current returns the rate", r.status_code == 200 and Decimal(str(r.json()["rate_per_g"])) == Decimal("6500"))
    # Newer rate wins
    client.post("/gold-rates", headers=auth, json={
        "rate_date": "2026-04-30", "currency": "PKR", "rate_per_g": "6750", "purity": 24,
    })
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24})
    check("newer rate becomes current", Decimal(str(r.json()["rate_per_g"])) == Decimal("6750"))
    # Different currency is independent
    client.post("/gold-rates", headers=auth, json={
        "rate_date": "2026-04-30", "currency": "USD", "rate_per_g": "85", "purity": 24,
    })
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "USD", "purity": 24})
    check("USD has its own current", Decimal(str(r.json()["rate_per_g"])) == Decimal("85"))
    # Delete the first rate
    r = client.delete(f"/gold-rates/{rate_id}", headers=auth)
    check("delete rate → 204", r.status_code == 204)

    # ----- STONES MASTER -----
    section("Stones master")
    r = client.post("/stones", headers=auth, json={
        "name": "VVS1 0.5ct round", "kind": "diamond", "cut": "round",
        "color": "F", "clarity": "VVS1", "default_rate_per_ct": "150000", "currency": "PKR",
    })
    check("create diamond → 201", r.status_code == 201)
    diamond_id = r.json()["id"]

    r = client.post("/stones", headers=auth, json={
        "name": "Royal Blue Sapphire", "kind": "sapphire", "cut": "oval",
        "color": "vivid blue", "clarity": "eye-clean", "default_rate_per_ct": "30000",
    })
    check("create sapphire → 201", r.status_code == 201)

    r = client.get("/stones", headers=auth, params={"kind": "diamond"})
    check("filter stones by kind", r.status_code == 200 and all(s["kind"] == "diamond" for s in r.json()))

    r = client.get("/stones", headers=auth, params={"q": "Royal"})
    check("search stones q=Royal", r.status_code == 200 and len(r.json()) >= 1)

    r = client.patch(f"/stones/{diamond_id}", headers=auth, json={"clarity": "VVS2"})
    check("PATCH stone.clarity", r.status_code == 200 and r.json()["clarity"] == "VVS2")

    # ----- PRODUCT STONES (per-product breakdown) -----
    section("Product stones")
    # Reuse p1 (auto-serial product created earlier)
    r = client.post(f"/products/{p1['id']}/stones", headers=auth, json={
        "stone_id": diamond_id, "quantity": 4, "weight_ct": "0.5",
    })
    check("attach stone (rate defaults from master) → 201", r.status_code == 201)
    # default_rate_per_ct on diamond = 150000, then we patched clarity but not rate
    check("rate snapshotted from default", Decimal(str(r.json()["rate_per_ct"])) == Decimal("150000"))
    ps_id = r.json()["id"]

    r = client.get(f"/products/{p1['id']}/stones", headers=auth)
    check("list product stones", r.status_code == 200 and len(r.json()) == 1)

    # Product detail now includes stones
    r = client.get(f"/products/{p1['id']}", headers=auth)
    check("product read includes stones[]", isinstance(r.json().get("stones"), list) and len(r.json()["stones"]) == 1)

    # Stone delete now requires password (Phase 8 alignment)
    r = client.delete(f"/stones/{diamond_id}", headers=auth)
    check("stone delete without password → 401", r.status_code == 401)
    # Cannot delete a stone that's in a product (even with password)
    r = client.delete(f"/stones/{diamond_id}", headers=pwd_h)
    check("stone delete blocked when used (FK RESTRICT)", r.status_code in (400, 409, 500))

    # Detach the stone, then delete is allowed (with password)
    r = client.delete(f"/products/{p1['id']}/stones/{ps_id}", headers=auth)
    check("detach stone → 204", r.status_code == 204)
    r = client.delete(f"/stones/{diamond_id}", headers=pwd_h)
    check("stone delete allowed once detached → 204", r.status_code == 204)

    # ----- MULTI-CURRENCY on invoices -----
    section("Multi-currency invoices")
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal",
        "currency": "USD", "gold_rate_per_g": "85",
        "items": [],
    })
    check("create USD invoice", r.status_code == 201 and r.json()["currency"] == "USD")
    pkr_inv = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal",
        "currency": "PKR", "gold_rate_per_g": "6500",
        "items": [],
    }).json()
    check("PKR invoice defaults preserved", pkr_inv["currency"] == "PKR")

    # ----- ALIGNMENT: gold-rate auto-fill + per-line discount -----
    section("Alignment")
    # Insert a rate dated far in the future so it sorts above any earlier rates.
    client.post("/gold-rates", headers=auth, json={
        "rate_date": "2099-12-31", "currency": "PKR", "rate_per_g": "7777", "purity": 24,
    })
    # Create invoice with NO gold_rate → backend should auto-fill from /current
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "items": [],
    })
    check(
        "invoice without rate auto-fills from /gold-rates/current",
        r.status_code == 201 and Decimal(str(r.json()["gold_rate_per_g"])) == Decimal("7777"),
        f"got rate {r.json().get('gold_rate_per_g')}",
    )

    # Per-line discount
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "gold_rate_per_g": "6000",
        "items": [{
            "description": "Gold bar",
            "gold_weight_g": "10", "gold_purity": 24,
            "labor_amount": "500",
            "line_discount": "200",
        }],
    })
    # gold = 10 × 24/24 × 6000 = 60000 ; line = 60000 + 0 + 500 - 200 = 60300
    check(
        "line_discount subtracts from line total",
        r.status_code == 201
        and Decimal(str(r.json()["items"][0]["line_total"])) == Decimal("60300.00"),
        f"got {r.json()['items'][0].get('line_total')}",
    )

    # Discount can't drive line negative
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "gold_rate_per_g": "6000",
        "items": [{
            "description": "Free gift", "gold_weight_g": "0",
            "labor_amount": "100", "line_discount": "999999",
        }],
    })
    check(
        "huge line_discount clamps to 0",
        r.status_code == 201
        and Decimal(str(r.json()["items"][0]["line_total"])) == Decimal("0.00"),
        f"got {r.json()['items'][0].get('line_total')}",
    )

    # ----- AUDIT LOG (admin viewer) -----
    section("Audit log")
    r = client.get("/audit-log", headers=auth)
    check("audit log readable by admin", r.status_code == 200)
    rows = r.json()
    actions = {row["action"] for row in rows}
    check(
        "issue invoice action recorded",
        "invoice.issue" in actions,
        f"actions={sorted(actions)}",
    )
    check("manufacturing.complete recorded", "manufacturing.complete" in actions)
    # Filter by action
    r = client.get("/audit-log", headers=auth, params={"action": "invoice.issue"})
    check(
        "filter audit by action",
        r.status_code == 200 and all(row["action"] == "invoice.issue" for row in r.json()),
    )
    # Staff cannot see audit log
    r = client.get("/audit-log", headers=staff_auth)
    check("audit log forbidden for staff → 403", r.status_code == 403)

    # ----- MATERIAL COST → real profit -----
    section("Material cost in profit")
    r = client.get(f"/products/{cost_product_id}", headers=auth)
    body = r.json()
    check(
        "cost-test product has material_cost ≥ 0",
        Decimal(str(body["material_cost"])) >= 0,
        f"material_cost={body['material_cost']}",
    )
    # Profit identity should still hold per currency.
    r = client.get("/reports/profit", headers=auth)
    pr = r.json()
    check(
        "profit identity per currency still holds",
        all(
            Decimal(str(b["profit"]))
            == (Decimal(str(b["revenue"])) - Decimal(str(b["making_cost"]))).quantize(Decimal("0.01"))
            for b in pr["by_currency"]
        ),
    )

    # ----- PHASE 1 CORRECTNESS FIXES (D2-D7) -----
    # D1 is covered inline in the manufacturing pipeline section above.
    section("Phase 1 correctness fixes")

    # --- D2: cancelling a job must not destroy the material issued to it ---
    inv_before = Decimal(str(client.get(f"/inventory/{raw_gold['id']}", headers=auth).json()["weight_g"]))
    cancel_job = client.post("/manufacturing", headers=auth, json={"notes": "cancel test"}).json()
    client.post(
        f"/manufacturing/{cancel_job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "10",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    inv_after_assign = Decimal(str(client.get(f"/inventory/{raw_gold['id']}", headers=auth).json()["weight_g"]))
    check("cancel test: 10g issued", inv_before - inv_after_assign == Decimal("10"))

    r = client.post(f"/manufacturing/{cancel_job['id']}/cancel", headers=auth, json={"reason": "no password"})
    check("cancel without password → 401 (D2)", r.status_code == 401, f"got {r.status_code}")

    r = client.post(
        f"/manufacturing/{cancel_job['id']}/cancel",
        headers=pwd_h,
        json={"gold_recovered_g": "999", "reason": "over-recovery"},
    )
    check("cancel recovering more than outstanding → 400 (D2)", r.status_code == 400, f"got {r.status_code}")

    # Recover 7 of the 10g; the remaining 3g stays outstanding against the karigar.
    r = client.post(
        f"/manufacturing/{cancel_job['id']}/cancel",
        headers=pwd_h,
        json={"gold_recovered_g": "7", "reason": "karigar returned partial, kept 3g"},
    )
    check("cancel with partial recovery → 200 (D2)", r.status_code == 200, f"got {r.status_code}")
    cancelled = r.json()
    check("cancelled stage", cancelled["stage"] == "cancelled")
    check(
        "unrecovered gold written off, not vanished (D2)",
        Decimal(str(cancelled["gold_written_off_g"])) == Decimal("3"),
        f"got {cancelled['gold_written_off_g']}",
    )
    check("cancel reason recorded (D2)", cancelled["cancel_reason"] is not None)
    inv_after_cancel = Decimal(str(client.get(f"/inventory/{raw_gold['id']}", headers=auth).json()["weight_g"]))
    check(
        "recovered gold returned to stock (D2)",
        inv_after_cancel - inv_after_assign == Decimal("7"),
        f"expected +7g, got +{inv_after_cancel - inv_after_assign}g",
    )
    r = client.post(f"/manufacturing/{cancel_job['id']}/cancel", headers=pwd_h, json={"reason": "again"})
    check("re-cancel blocked → 409", r.status_code == 409, f"got {r.status_code}")

    # --- D3: attaching a stone must not re-price the product's gold ---
    d3_job = client.post("/manufacturing", headers=auth, json={"notes": "rate lock test"}).json()
    client.post(
        f"/manufacturing/{d3_job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "10",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    client.post(f"/manufacturing/{d3_job['id']}/receive-karigar", headers=auth, json={"jewelry_received_g": "10"})
    d3_prod_id = client.post(
        f"/manufacturing/{d3_job['id']}/complete",
        headers=pwd_h,
        json={"product_name": "Rate Lock Ring", "category": "ring"},
    ).json()["product_id"]

    d3_before = client.get(f"/products/{d3_prod_id}", headers=auth).json()
    locked_rate = d3_before.get("gold_rate_at_cost")
    material_before = Decimal(str(d3_before["material_cost"]))
    check("gold rate locked on product at completion (D3)", locked_rate is not None, str(locked_rate))

    # Move the market: publish a much higher rate for today.
    client.post(
        "/gold-rates",
        headers=auth,
        json={"rate_date": date.today().isoformat(), "currency": "PKR", "rate_per_g": "99999", "purity": 24},
    )
    # Attaching a stone recomputes material_cost — the stone must be added, but
    # the gold underneath must stay valued at the locked rate.
    stone_id = client.get("/stones", headers=auth).json()[0]["id"]
    r = client.post(
        f"/products/{d3_prod_id}/stones",
        headers=auth,
        json={"stone_id": stone_id, "quantity": 1, "weight_ct": "1", "rate_per_ct": "100"},
    )
    check("attach stone for rate-lock test → 201", r.status_code == 201, f"got {r.status_code}")
    d3_after = client.get(f"/products/{d3_prod_id}", headers=auth).json()
    check(
        "locked rate unchanged after recompute (D3)",
        str(d3_after.get("gold_rate_at_cost")) == str(locked_rate),
        f"{locked_rate} -> {d3_after.get('gold_rate_at_cost')}",
    )
    check(
        "material_cost grew by exactly the stone value, gold not re-priced (D3)",
        Decimal(str(d3_after["material_cost"])) - material_before == Decimal("100.00"),
        f"delta={Decimal(str(d3_after['material_cost'])) - material_before}, expected 100.00",
    )

    # --- D5: a piece may legitimately come back heavier than the gold issued ---
    d5_job = client.post("/manufacturing", headers=auth, json={"notes": "weight gain"}).json()
    client.post(
        f"/manufacturing/{d5_job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "10",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    r = client.post(
        f"/manufacturing/{d5_job['id']}/receive-karigar",
        headers=auth,
        json={"jewelry_received_g": "10.5"},
    )
    check("receive heavier than issued is allowed (D5)", r.status_code == 200, f"got {r.status_code}")
    check(
        "weight gain recorded as negative loss (D5)",
        Decimal(str(r.json()["karigar_loss_g"])) == Decimal("-0.5"),
        f"got {r.json()['karigar_loss_g']}",
    )
    client.post(
        f"/manufacturing/{d5_job['id']}/assign-polish",
        headers=auth,
        json={"polish_vendor_id": polisher["id"], "weight_before_polish_g": "10.5"},
    )
    r = client.post(
        f"/manufacturing/{d5_job['id']}/receive-polish",
        headers=auth,
        json={"weight_after_polish_g": "10.6"},
    )
    check("polish weight gain allowed (D5)", r.status_code == 200, f"got {r.status_code}")

    # --- D6: deleting a product must not make the next serial collide ---
    # Mint three in a row, then delete the *middle* one. A count-based generator
    # now returns the third product's own number and dies on the unique index;
    # a max-based one moves past it. (Reusing the number of a row that no longer
    # exists is harmless — colliding with one that still does is the bug.)
    serial_products = [
        client.post(
            "/products",
            headers=auth,
            json={"name": f"Serial Probe {i}", "gold_weight_g": "1", "gold_purity": 22},
        ).json()
        for i in range(3)
    ]
    live_serials = {p["serial_no"] for p in serial_products}
    r = client.delete(f"/products/{serial_products[1]['id']}", headers=pwd_h)
    check("delete middle product for serial test → 204", r.status_code == 204, f"got {r.status_code}")
    live_serials.discard(serial_products[1]["serial_no"])

    r = client.post(
        "/products",
        headers=auth,
        json={"name": "After Middle Deletion", "gold_weight_g": "1", "gold_purity": 22},
    )
    check(
        "serial mint survives a deletion mid-sequence (D6)",
        r.status_code == 201,
        f"got {r.status_code}: {r.text[:200]}",
    )
    check(
        "new serial does not collide with a live one (D6)",
        r.status_code == 201 and r.json()["serial_no"] not in live_serials,
        f"{r.json().get('serial_no')} vs live {sorted(live_serials)}",
    )

    # --- D7: stock deduction follows the product, not the typed line weight ---
    d7_job = client.post("/manufacturing", headers=auth, json={"notes": "issue weight"}).json()
    client.post(
        f"/manufacturing/{d7_job['id']}/assign-karigar",
        headers=auth,
        json={
            "karigar_id": karigar["id"],
            "gold_assigned_g": "8",
            "gold_assigned_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    client.post(f"/manufacturing/{d7_job['id']}/receive-karigar", headers=auth, json={"jewelry_received_g": "8"})
    d7_prod_id = client.post(
        f"/manufacturing/{d7_job['id']}/complete",
        headers=pwd_h,
        json={"product_name": "Issue Weight Ring", "category": "ring", "finished_inventory_location": "showroom"},
    ).json()["product_id"]

    # Bill a wildly different weight than the piece actually carries. Previously
    # this either drifted the snapshot or tripped the negative-stock guard.
    d7_inv = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": customer_id,
            "sale_type": "normal",
            "currency": "PKR",
            "items": [{
                "product_id": d7_prod_id,
                "description": "Overstated weight on purpose",
                "quantity": 1,
                "gold_weight_g": "500",
                "gold_purity": 22,
            }],
        },
    ).json()
    r = client.post(f"/invoices/{d7_inv['id']}/issue", headers=pwd_h)
    check(
        "issue succeeds despite line weight ≠ product weight (D7)",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    finished = client.get("/inventory", headers=auth, params={"type": "finished_product"}).json()
    d7_row = next((it for it in finished if it.get("product_id") == d7_prod_id), None)
    check(
        "inventory zeroed by product weight, not line weight (D7)",
        d7_row is not None
        and d7_row["quantity"] == 0
        and Decimal(str(d7_row["weight_g"])) == Decimal("0"),
        str(d7_row),
    )

    # ----- LOGIN RATE LIMIT (slowapi: 10/minute) -----
    section("Login rate limit")
    for _ in range(10):
        client.post("/auth/login", json={"email": "admin@jewelryerp.com", "password": "wrong"})
    r = client.post("/auth/login", json={"email": "admin@jewelryerp.com", "password": "wrong"})
    check(
        "11th login attempt within a minute → 429",
        r.status_code == 429,
        f"got {r.status_code}",
    )

    # ----- LIST/FILTER ENDPOINTS -----
    section("List filters")
    r = client.get("/stock-movements", headers=auth, params={"type": "manufacturing_out"})
    check("filter ledger by type", r.status_code == 200 and all(m["type"] == "manufacturing_out" for m in r.json()))

    r = client.get("/manufacturing", headers=auth, params={"stage": "completed"})
    check("filter manufacturing by stage", r.status_code == 200 and all(j["stage"] == "completed" for j in r.json()))

    r = client.get("/invoices", headers=auth, params={"status": "paid"})
    check("filter invoices by status", r.status_code == 200 and all(i["status"] == "paid" for i in r.json()))

    # ----- SUMMARY -----
    print()
    fails = [r for r in results if r[0] == FAIL]
    print(f"\n{'='*60}")
    print(f"Total: {len(results)}  Pass: {len(results) - len(fails)}  Fail: {len(fails)}")
    for r in fails:
        print(" -", r[1], "::", r[2])
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
