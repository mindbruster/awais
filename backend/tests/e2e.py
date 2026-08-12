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


def preflight(client: httpx.Client, auth: dict[str, str]) -> str | None:
    """
    Refuse to run against a database that has already been used.

    This suite mints serial numbers, asserts on running balances and creates
    master data by a fixed name, so a second run against the same database
    fails in ways that look like product bugs and are not: a 409 on a
    department that already exists, a balance that includes the previous run's
    invoices. The first such failure then usually takes the whole run down with
    a KeyError, because the assertion after it reads a field off an error body.

    Cheaper to say so up front. Returns the reason, or None if the database
    looks freshly seeded.
    """
    for path, label in (
        ("/ledger/journal", "journal entries"),
        ("/designs", "designs"),
        ("/invoices", "invoices"),
    ):
        r = client.get(path, headers=auth, params={"limit": 1})
        if r.status_code != 200:
            continue
        body = r.json()
        rows = body.get("items", body) if isinstance(body, dict) else body
        if isinstance(rows, list) and rows:
            return f"the database already has {label} in it"
    return None


def main() -> int:
    client = httpx.Client(base_url=API, timeout=30)

    # ----- AUTH -----
    section("Auth")
    r = client.post("/auth/login", json={"email": "admin@jewelryerp.com", "password": "admin123"})
    check("admin login → 200", r.status_code == 200, str(r.status_code))
    token = r.json().get("access_token")
    check("login returns token", bool(token))
    auth = {"Authorization": f"Bearer {token}"}

    dirty = preflight(client, auth) if token else None
    if dirty:
        print(
            f"\n  This suite needs a freshly seeded database, and {dirty}.\n"
            "  Rebuild it, then run again:\n\n"
            "      npm run db:fresh\n\n"
            "  (That drops and recreates whichever database DATABASE_URL points at,\n"
            "  re-runs the migrations and re-seeds the admin user.)\n"
        )
        return 2

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

    # ----- THE RETIRED MANUFACTURING MODULE -----
    section("Retired manufacturing module")
    # The three-stage job module was replaced by the routing engine and its API
    # is gone. It posted no journal entries, so metal could pass through it and
    # never reach the books — which is why leaving it reachable was the actual
    # defect, not the duplication. Its table survives for the loss report's
    # `legacy` rows; nothing writes to it.
    for path, verb in (("/manufacturing", "list"), ("/manufacturing/1", "read")):
        r = client.get(path, headers=auth)
        check(f"{verb} retired job endpoint → 404", r.status_code == 404, f"got {r.status_code}")
    r = client.post("/manufacturing", headers=auth, json={"notes": "should not exist"})
    check("opening a job on the retired module → 404", r.status_code == 404, f"got {r.status_code}")
    r = client.get("/reports/manufacturing-loss", headers=auth)
    check(
        "the loss report still reads the retired table",
        r.status_code == 200,
        "history has to stay legible after the module goes",
    )

    # Two finished pieces the sales sections below sell. They used to be minted
    # by completing a job; a piece that came in before the shop had the system,
    # or was bought in finished, arrives exactly this way.
    fp = client.post("/products", headers=auth, json={
        "name": "Finished Test Ring", "category": "ring",
        "gold_weight_g": "9.6", "gold_purity": 22, "stone_weight_ct": "1.8",
    })
    check("create a finished piece → 201", fp.status_code == 201, f"got {fp.status_code}")
    finished_product_id = fp.json()["id"]
    r = client.post("/inventory", headers=auth, json={
        "type": "finished_product", "label": "Finished Test Ring",
        "location": "showroom", "quantity": 1,
        "weight_g": "9.6", "weight_ct": "1.8", "purity": 22,
        "product_id": finished_product_id,
    })
    check("stock it as finished goods → 201", r.status_code == 201, f"got {r.status_code}")
    finished_inv = r.json()
    check(
        "finished-goods inventory carries the piece's weights",
        finished_inv["quantity"] == 1
        and Decimal(str(finished_inv["weight_g"])) == Decimal("9.6")
        and Decimal(str(finished_inv["weight_ct"])) == Decimal("1.8"),
        str(finished_inv),
    )

    cp = client.post("/products", headers=auth, json={
        "name": "Cost-test ring", "category": "ring",
        "gold_weight_g": "4.9", "gold_purity": 22,
    })
    cost_product_id = cp.json()["id"]
    r = client.patch(f"/products/{cost_product_id}", headers=auth, json={"total_cost": "260"})
    check(
        "making cost recorded on the piece",
        r.status_code == 200 and Decimal(str(r.json()["total_cost"])) == Decimal("260.00"),
        f"got {r.status_code}: {r.json().get('total_cost')}",
    )

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
    # A second finished piece, so the approval flow has its own stock to leave
    # alone. What matters here is that it is in finished goods at qty 1.
    p2_id = client.post("/products", headers=auth, json={
        "name": "Ring 2", "category": "ring", "gold_weight_g": "7.9", "gold_purity": 22,
    }).json()["id"]
    p2_inv = client.post("/inventory", headers=auth, json={
        "type": "finished_product", "label": "Ring 2", "location": "showroom",
        "quantity": 1, "weight_g": "7.9", "purity": 22, "product_id": p2_id,
    }).json()
    check("ring 2 inventory has qty 1", p2_inv.get("quantity") == 1, str(p2_inv)[:120])

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

    # These two take dates and widen the closing day server-side. They used to
    # take instants, and the caller did the widening — so this pins the shape
    # the UI has to send. Getting it wrong is a 422 on a panel that then renders
    # an error where a number should be, which no API-level assertion about
    # totals would ever notice.
    for path in ("/reports/sales", "/reports/profit"):
        r = client.get(f"{path}?range_from=2025-09-01&range_to=2026-12-31", headers=auth)
        check(f"{path} takes plain dates → 200", r.status_code == 200, f"got {r.status_code}")
        r = client.get(f"{path}?range_to=2026-12-31T23:59:59Z", headers=auth)
        check(
            f"{path} refuses an instant → 422",
            r.status_code == 422,
            f"got {r.status_code} — if this ever passes again, the UI may be sending instants",
        )

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
    # Nothing has been through the bench yet in this run, so the aggregates are
    # legitimately zero here — the routing section below asserts they fill in.
    # What matters at this point is that the retired table contributes nothing:
    # a non-zero legacy figure would mean something is still writing to it.
    check(
        "the retired manufacturing table contributes nothing",
        Decimal(str(lr["legacy_loss_g"])) == 0,
        f"legacy_loss_g={lr['legacy_loss_g']} — nothing should write there any more",
    )

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
    # Today's rate, keyed after the earlier ones so it wins the tie on date.
    # Deliberately not future-dated: a rate entered in advance is a plan, not a
    # price, and is excluded from "current" — see services/gold_rate.py.
    client.post("/gold-rates", headers=auth, json={
        "rate_date": date.today().isoformat(), "currency": "PKR", "rate_per_g": "7777", "purity": 24,
    })
    client.post("/gold-rates", headers=auth, json={
        "rate_date": "2099-12-31", "currency": "PKR", "rate_per_g": "999999", "purity": 24,
    })
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24})
    check(
        "a forward-dated rate is not treated as current",
        Decimal(str(r.json()["rate_per_g"])) == Decimal("7777"),
        f"got {r.json().get('rate_per_g')} — a rate keyed for a future date must not price today",
    )
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
    # Destructive actions matter most here — an issue can be inferred from the
    # invoice, but a deletion leaves nothing behind except this row.
    check(
        "deleting a product is recorded",
        "product.delete" in actions,
        f"actions={sorted(actions)}",
    )
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

    # --- D3: attaching a stone must not re-price the product's gold ---
    # The rate is locked the first time a piece is costed and reused on every
    # later pass, so recomputing only ever re-values the stones. Re-pricing the
    # gold would rewrite the piece's historical cost, and every profit figure
    # that references it, every time the market moved.
    d3_prod_id = client.post("/products", headers=auth, json={
        "name": "Rate Lock Ring", "category": "ring",
        "gold_weight_g": "10", "gold_purity": 22,
    }).json()["id"]
    stone_id = client.get("/stones", headers=auth).json()[0]["id"]
    # The first attach is what locks the rate.
    client.post(
        f"/products/{d3_prod_id}/stones",
        headers=auth,
        json={"stone_id": stone_id, "quantity": 1, "weight_ct": "1", "rate_per_ct": "100"},
    )
    d3_before = client.get(f"/products/{d3_prod_id}", headers=auth).json()
    locked_rate = d3_before.get("gold_rate_at_cost")
    material_before = Decimal(str(d3_before["material_cost"]))
    check("gold rate locked on the piece when it was costed (D3)", locked_rate is not None, str(locked_rate))

    # Move the market hard. If the gold re-prices, material_cost jumps by the
    # whole difference on 10g and the delta below is nowhere near 100.
    client.post(
        "/gold-rates",
        headers=auth,
        json={"rate_date": date.today().isoformat(), "currency": "PKR", "rate_per_g": "99999", "purity": 24},
    )
    r = client.post(
        f"/products/{d3_prod_id}/stones",
        headers=auth,
        json={"stone_id": stone_id, "quantity": 1, "weight_ct": "1", "rate_per_ct": "100"},
    )
    check("attach a second stone after the rate moved → 201", r.status_code == 201, f"got {r.status_code}")
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
    d7_prod_id = client.post("/products", headers=auth, json={
        "name": "Issue Weight Ring", "category": "ring",
        "gold_weight_g": "8", "gold_purity": 22,
    }).json()["id"]
    client.post("/inventory", headers=auth, json={
        "type": "finished_product", "label": "Issue Weight Ring", "location": "showroom",
        "quantity": 1, "weight_g": "8", "purity": 22, "product_id": d7_prod_id,
    })

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
    # Void it now it has proved its point. The line deliberately bills a weight
    # the piece does not have, which is exactly what the margin report reports
    # as unattributable — leaving it behind makes every margin figure on the dev
    # database look broken for a reason that is only ever true in this test.
    r = client.post(f"/invoices/{d7_inv['id']}/void", headers=pwd_h)
    check("void the deliberately mismatched D7 invoice", r.status_code == 200, f"got {r.status_code}: {r.text[:160]}")

    # ----- MASTER DATA (phase 2) -----
    section("Master data")

    # Departments ship seeded so a fresh install is usable immediately.
    r = client.get("/departments", headers=auth)
    depts = r.json()
    check("9 departments seeded", r.status_code == 200 and len(depts) == 9, f"got {len(depts)}")
    check(
        "departments ordered by sequence",
        [d["code"] for d in depts][:3] == ["RP", "CAST", "CLEAN"],
        str([d["code"] for d in depts][:3]),
    )
    setting = next((d for d in depts if d["code"] == "SET"), None)
    check("setting is the stone-consuming stage", setting and setting["consumes_stones"] is True)

    r = client.post("/departments", headers=auth, json={"name": "Enamel", "code": "enml", "sequence": 95})
    check("create department → 201", r.status_code == 201, f"got {r.status_code}")
    check("department code upper-cased", r.json()["code"] == "ENML", r.json()["code"])
    enamel_id = r.json()["id"]
    r = client.post("/departments", headers=auth, json={"name": "Enamel 2", "code": "ENML"})
    check("duplicate department code → 409", r.status_code == 409, f"got {r.status_code}")

    # Items — the abbreviation seeds design numbers, so it is normalised and unique.
    r = client.post("/items", headers=auth, json={"name": "Taka", "abbreviation": "tk"})
    check("create item → 201", r.status_code == 201, f"got {r.status_code}")
    check("item abbreviation upper-cased", r.json()["abbreviation"] == "TK", r.json()["abbreviation"])
    r = client.post("/items", headers=auth, json={"name": "Another Taka", "abbreviation": "TK"})
    check("duplicate item abbreviation → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.post("/items", headers=auth, json={"name": "Bad", "abbreviation": "T-K!"})
    check("non-alphanumeric abbreviation → 422", r.status_code == 422, f"got {r.status_code}")
    r = client.get("/items", headers=auth, params={"q": "tak"})
    check("item search matches", r.status_code == 200 and len(r.json()) >= 1)

    # Attribute options replace the free-text cut/colour/clarity columns.
    r = client.get("/attribute-options/by-kind/clarity", headers=auth)
    clarities = r.json()
    check("clarity options seeded", r.status_code == 200 and len(clarities) == 11, f"got {len(clarities)}")
    check("clarity options sorted", clarities[0]["value"] == "FL", clarities[0]["value"])
    r = client.get("/attribute-options/by-kind/quality", headers=auth)
    check(
        "diamond quality grades seeded",
        {o["value"] for o in r.json()} == {"Deluxe", "Commercial"},
        str([o["value"] for o in r.json()]),
    )
    r = client.post("/attribute-options", headers=auth, json={"kind": "clarity", "value": "FL"})
    check("duplicate option within a kind → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.post("/attribute-options", headers=auth, json={"kind": "cut", "value": "FL"})
    check("same value under a different kind is fine → 201", r.status_code == 201, f"got {r.status_code}")

    # Countries and cities — city names repeat across countries.
    pk = client.post("/countries", headers=auth, json={"name": "Pakistan", "iso_code": "pk"}).json()
    check("country iso upper-cased", pk["iso_code"] == "PK", str(pk.get("iso_code")))
    india = client.post("/countries", headers=auth, json={"name": "India"}).json()
    r = client.post("/cities", headers=auth, json={"name": "Karachi", "country_id": pk["id"]})
    check("create city → 201", r.status_code == 201, f"got {r.status_code}")
    karachi_id = r.json()["id"]
    check("city read carries country name", r.json()["country_name"] == "Pakistan", str(r.json()))
    r = client.post("/cities", headers=auth, json={"name": "Karachi", "country_id": pk["id"]})
    check("duplicate city in same country → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.post("/cities", headers=auth, json={"name": "Hyderabad", "country_id": pk["id"]})
    r2 = client.post("/cities", headers=auth, json={"name": "Hyderabad", "country_id": india["id"]})
    check(
        "same city name in a different country is allowed",
        r.status_code == 201 and r2.status_code == 201,
        f"{r.status_code}/{r2.status_code}",
    )
    r = client.delete(f"/countries/{pk['id']}", headers=pwd_h)
    check("delete country with cities → 409", r.status_code == 409, f"got {r.status_code}")

    # Banks carry the deduction rate; accounts carry the opening cash.
    bank = client.post(
        "/banks", headers=auth, json={"name": "Meezan", "deduction_rate": "0.5"}
    ).json()
    r = client.post(
        "/bank-accounts",
        headers=auth,
        json={
            "bank_id": bank["id"],
            "account_no": "0123456789",
            "title": "Main current",
            "opening_balance": "2000000",
        },
    )
    check("create bank account → 201", r.status_code == 201, f"got {r.status_code}")
    check("bank account read carries bank name", r.json()["bank_name"] == "Meezan", str(r.json()))
    check("opening balance stored", Decimal(str(r.json()["opening_balance"])) == Decimal("2000000"))
    r = client.post(
        "/bank-accounts", headers=auth, json={"bank_id": bank["id"], "account_no": "0123456789"}
    )
    check("duplicate account no on same bank → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.delete(f"/banks/{bank['id']}", headers=pwd_h)
    check("delete bank with accounts → 409", r.status_code == 409, f"got {r.status_code}")

    # Customers gained the counter fields.
    r = client.post(
        "/customers",
        headers=auth,
        json={
            "name": "Sagar Jalal",
            "cnic": "42101-1234567-1",
            "phone2": "03001234567",
            "reference": "Hanif Jeweller",
            "date_of_birth": "1985-04-12",
            "city_id": karachi_id,
            "country_id": pk["id"],
            "opening_balance": "50000",
        },
    )
    check("create customer with extended fields → 201", r.status_code == 201, f"got {r.status_code}")
    cust = r.json()
    check("customer city/country names resolved", cust["city_name"] == "Karachi" and cust["country_name"] == "Pakistan", str(cust))
    check("customer opening balance stored", Decimal(str(cust["opening_balance"])) == Decimal("50000"))
    r = client.post("/customers", headers=auth, json={"name": "Bare Minimum"})
    check("name alone is still enough to create a customer", r.status_code == 201, f"got {r.status_code}")

    # Workers gained a department, agreed wastage and opening balances.
    casting_id = next(d["id"] for d in depts if d["code"] == "CAST")
    r = client.post(
        "/vendors",
        headers=auth,
        json={
            "name": "Zahid Bhai",
            "type": "karigar",
            "department_id": casting_id,
            "default_wastage_pct": "3.5",
            "opening_gold_g": "12.5",
            "cnic": "42101-7654321-9",
        },
    )
    check("create worker with department → 201", r.status_code == 201, f"got {r.status_code}")
    w = r.json()
    check("worker department name resolved", w["department_name"] == "Casting", str(w))
    check("worker opening gold stored", Decimal(str(w["opening_gold_g"])) == Decimal("12.5"))
    check(
        "worker's own wastage wins",
        Decimal(str(w["effective_wastage_pct"])) == Decimal("3.5"),
        str(w["effective_wastage_pct"]),
    )
    client.patch(f"/departments/{enamel_id}", headers=auth, json={"default_wastage_pct": "2.0"})
    r = client.post(
        "/vendors",
        headers=auth,
        json={"name": "Inherits Dept Rate", "type": "other", "department_id": enamel_id},
    )
    check(
        "worker with no rate inherits the department's",
        Decimal(str(r.json()["effective_wastage_pct"])) == Decimal("2.0"),
        str(r.json().get("effective_wastage_pct")),
    )
    r = client.delete(f"/departments/{casting_id}", headers=pwd_h)
    check("delete department with workers → 409", r.status_code == 409, f"got {r.status_code}")

    # Stones gained category / abbreviation / quality.
    r = client.post(
        "/stones",
        headers=auth,
        json={
            "name": "12 PTR",
            "kind": "diamond",
            "category": "diamond",
            "abbreviation": "D12",
            "quality": "Commercial",
            "cut": "Round",
            "clarity": "VS1",
        },
    )
    check("create diamond with category/quality → 201", r.status_code == 201, f"got {r.status_code}")
    check("stone category stored", r.json()["category"] == "diamond", str(r.json().get("category")))
    check("stone quality stored", r.json()["quality"] == "Commercial")

    # RBAC — staff select from masters but must not redefine them.
    r = client.get("/departments", headers=staff_auth)
    check("staff can read masters", r.status_code == 200, f"got {r.status_code}")
    r = client.post("/departments", headers=staff_auth, json={"name": "Sneaky", "code": "SNK"})
    check("staff cannot create masters → 403", r.status_code == 403, f"got {r.status_code}")
    r = client.post("/items", headers=acct_auth, json={"name": "Bangle", "abbreviation": "BNG"})
    check("accountant can create masters → 201", r.status_code == 201, f"got {r.status_code}")
    r = client.delete(f"/items/{r.json()['id']}", headers={**acct_auth, "X-Confirm-Password": "acct1234"})
    check("accountant cannot delete masters → 403", r.status_code == 403, f"got {r.status_code}")

    # ----- LEDGER (phase 3) -----
    section("Ledger")

    r = client.get("/ledger/accounts", headers=auth)
    accounts = r.json()
    by_code = {a["code"]: a for a in accounts}
    check(
        "chart of accounts seeded",
        r.status_code == 200 and len(accounts) == 25,
        f"got {len(accounts)}",
    )
    check(
        "there is a head to relieve the cost of a sale to",
        "5400" in by_code and by_code["5400"]["is_system"],
        "1150 Finished Goods would grow forever without one",
    )
    check(
        "system heads flagged and postable",
        by_code["1130"]["is_system"] and by_code["1130"]["is_postable"],
        str(by_code.get("1130")),
    )
    check("headings are not postable", by_code["1000"]["is_postable"] is False)
    check("parent resolved", by_code["1110"]["parent_name"] == "Current Assets", str(by_code["1110"]))

    # System accounts are resolved by code at post time, so the code must be frozen.
    r = client.patch(f"/ledger/accounts/{by_code['1130']['id']}", headers=auth, json={"code": "9999"})
    check("cannot recode a system account → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.delete(f"/ledger/accounts/{by_code['1130']['id']}", headers=pwd_h)
    check("cannot delete a system account → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.delete(f"/ledger/accounts/{by_code['1100']['id']}", headers=pwd_h)
    check("cannot delete an account with children → 409", r.status_code == 409, f"got {r.status_code}")

    r = client.post(
        "/ledger/accounts",
        headers=auth,
        json={"code": "5310", "name": "Shop Rent", "type": "expense", "parent_id": by_code["5000"]["id"]},
    )
    check("create a child account → 201", r.status_code == 201, f"got {r.status_code}")
    rent_id = r.json()["id"]

    # --- the invariant: an entry that doesn't net to zero must be refused ---
    r = client.post(
        "/ledger/entries",
        headers=pwd_h,
        json={
            "memo": "deliberately unbalanced",
            "postings": [
                {"account_code": "1110", "quantity": "1000"},
                {"account_code": "5310", "quantity": "-900"},
            ],
        },
    )
    check("unbalanced entry refused → 400", r.status_code == 400, f"got {r.status_code}: {r.text[:160]}")

    r = client.post(
        "/ledger/entries",
        headers=auth,
        json={
            "memo": "no password",
            "postings": [
                {"account_code": "1110", "quantity": "100"},
                {"account_code": "3100", "quantity": "-100"},
            ],
        },
    )
    check("manual entry without password → 401", r.status_code == 401, f"got {r.status_code}")

    # Measured as a delta, not an absolute: sales now settle through the ledger
    # too, so the shop's cash is not only what this section put there.
    cash_before = Decimal(
        str(client.get("/ledger/position", headers=auth).json()["cash_in_hand"])
    )

    # Capital injection: 500,000 cash in, against capital.
    r = client.post(
        "/ledger/entries",
        headers=pwd_h,
        json={
            "memo": "Owner capital injection",
            "postings": [
                {"account_code": "1110", "quantity": "500000", "memo": "cash in"},
                {"account_code": "3100", "quantity": "-500000"},
            ],
        },
    )
    check("balanced cash entry → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    cap_entry = r.json()
    check("entry numbered JE-YY-NNNNN", cap_entry["entry_no"].startswith("JE-26-"), cap_entry["entry_no"])
    check(
        "debits equal credits on the entry",
        Decimal(str(cap_entry["total_debit"])) == Decimal(str(cap_entry["total_credit"])) == Decimal("500000"),
        f"{cap_entry['total_debit']} vs {cap_entry['total_credit']}",
    )

    # --- multi-commodity: gold bought for cash, balancing on PKR value ---
    # 100g of 22k = 91.6667 fine grams. At 7777/fine gram that is 712,833.55.
    gold_value = (Decimal("91.6667") * Decimal("7777")).quantize(Decimal("0.01"))
    r = client.post(
        "/ledger/entries",
        headers=pwd_h,
        json={
            "memo": "Bought 100g of 22k bullion for cash",
            # The counter sends what the scale said (100g) and the karat stamp.
            # Converting to fine grams is the server's job — a human has a
            # weight and a purity, not a 24k equivalent.
            "postings": [
                {
                    "account_code": "1130",
                    "commodity": "GOLD",
                    "quantity": "100",
                    "native_purity": 22,
                    "rate": "7777",
                },
                {"account_code": "1110", "quantity": str(-gold_value)},
            ],
        },
    )
    check(
        "gold and cash balance on PKR value, not on quantity → 201",
        r.status_code == 201,
        f"got {r.status_code}: {r.text[:250]}",
    )
    gold_line = next(
        (ln for ln in r.json().get("lines", []) if ln["commodity"] == "GOLD"), {}
    ) if r.status_code == 201 else {}
    check(
        "as-weighed grams converted to fine, with the original kept alongside",
        Decimal(str(gold_line.get("quantity", 0))) == Decimal("91.6667")
        and Decimal(str(gold_line.get("native_weight_g", 0))) == Decimal("100")
        and gold_line.get("native_purity") == 22,
        f"22k must not be banked as pure — got {gold_line}",
    )

    # A gold line priced at zero would balance against nothing and post metal for free.
    r = client.post(
        "/ledger/entries",
        headers=pwd_h,
        json={
            "memo": "gold at no value",
            "postings": [
                {"account_code": "1130", "commodity": "GOLD", "quantity": "10", "rate": "0"},
                {"account_code": "1110", "quantity": "0"},
            ],
        },
    )
    check("gold line with a zero rate refused → 422", r.status_code == 422, f"got {r.status_code}")

    # --- position reads from the journal, not from stored columns ---
    r = client.get("/ledger/position", headers=auth)
    pos = r.json()
    check(
        "cash moved by the capital put in less the bullion paid for",
        Decimal(str(pos["cash_in_hand"])) - cash_before == (Decimal("500000") - gold_value),
        f"moved {Decimal(str(pos['cash_in_hand'])) - cash_before}, "
        f"expected {Decimal('500000') - gold_value}",
    )
    check(
        "gold in hand carried in fine grams",
        Decimal(str(pos["gold_in_hand_g"])) == Decimal("91.6667"),
        f"got {pos['gold_in_hand_g']}",
    )

    # --- statement: opening balance, running balance, closing ---
    r = client.get("/ledger/statement", headers=auth, params={"account_code": "1110"})
    st = r.json()
    check("statement returns rows", r.status_code == 200 and len(st["rows"]) >= 2, str(r.status_code))
    check(
        "running balance ends at the closing balance",
        Decimal(str(st["rows"][-1]["running_balance"])) == Decimal(str(st["closing_balance"])),
        f"{st['rows'][-1]['running_balance']} vs {st['closing_balance']}",
    )
    check(
        "closing = opening + debits - credits",
        Decimal(str(st["closing_balance"]))
        == Decimal(str(st["opening_balance"])) + Decimal(str(st["period_debit"])) - Decimal(str(st["period_credit"])),
        str(st),
    )
    check(
        "statement names the counter-account",
        any("Capital" in " ".join(row["counter_accounts"]) for row in st["rows"]),
        str([row["counter_accounts"] for row in st["rows"]]),
    )
    r = client.get("/ledger/statement", headers=auth)
    check("statement without an account → 400", r.status_code == 400, f"got {r.status_code}")

    # --- trial balance ---
    r = client.get("/ledger/trial-balance", headers=auth)
    tb = r.json()
    check("trial balance is balanced", r.status_code == 200 and tb["balanced"] is True, str(tb.get("balanced")))
    check(
        "total debits equal total credits in PKR",
        Decimal(str(tb["total_debit_pkr"])) == Decimal(str(tb["total_credit_pkr"])),
        f"{tb['total_debit_pkr']} vs {tb['total_credit_pkr']}",
    )
    check(
        "gold sits on its own trial-balance row",
        any(row["commodity"] == "GOLD" for row in tb["rows"]),
        str([r_["commodity"] for r_ in tb["rows"]]),
    )

    # --- reversal, not editing ---
    r = client.post(f"/ledger/entries/{cap_entry['id']}/reverse", headers=pwd_h, json={"memo": "keyed twice"})
    check("reverse an entry → 201", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:200]}")
    rev = r.json()
    check("reversal points back at the original", rev["reverses_entry_id"] == cap_entry["id"], str(rev.get("reverses_entry_id")))
    r = client.post(f"/ledger/entries/{cap_entry['id']}/reverse", headers=pwd_h, json={"memo": "again"})
    check("double reversal refused → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.post(f"/ledger/entries/{rev['id']}/reverse", headers=pwd_h, json={"memo": "reverse the reversal"})
    check("reversing a reversal refused → 409", r.status_code == 409, f"got {r.status_code}")
    r = client.get("/ledger/trial-balance", headers=auth)
    check("still balanced after the reversal", r.json()["balanced"] is True)

    # --- opening balances move master-record numbers into the books ---
    r = client.post("/ledger/opening-balances", headers=pwd_h)
    check("post opening balances → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    ob = r.json()
    posted_first = len(ob["posted"])
    check("opening balances posted for the declared parties", posted_first >= 2, f"posted {posted_first}")
    # Sagar Jalal was created with a 50,000 opening balance earlier in this run.
    r = client.get(
        "/ledger/statement",
        headers=auth,
        params={"account_code": "1210", "party_type": "customer", "party_id": cust["id"]},
    )
    check(
        "customer opening balance is now a real ledger balance",
        Decimal(str(r.json()["closing_balance"])) == Decimal("50000"),
        f"got {r.json()['closing_balance']}",
    )
    # Zahid Bhai was created holding 12.5g. At 22k that is not what he holds —
    # opening gold is declared as fine metal, so it carries across unchanged.
    r = client.get(
        "/ledger/statement",
        headers=auth,
        params={"account_code": "1160", "party_type": "worker", "party_id": w["id"], "commodity": "GOLD"},
    )
    check(
        "worker opening gold is now a metal balance",
        Decimal(str(r.json()["closing_balance"])) == Decimal("12.5"),
        f"got {r.json()['closing_balance']}",
    )

    r = client.post("/ledger/opening-balances", headers=pwd_h)
    check(
        "re-running opening balances posts nothing (idempotent)",
        r.status_code == 200 and len(r.json()["posted"]) == 0 and len(r.json()["skipped"]) >= posted_first,
        f"posted={len(r.json()['posted'])} skipped={len(r.json()['skipped'])}",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("still balanced after opening balances", r.json()["balanced"] is True)

    # --- RBAC: the books are not staff information ---
    r = client.get("/ledger/position", headers=staff_auth)
    check("staff cannot read the ledger → 403", r.status_code == 403, f"got {r.status_code}")
    r = client.get("/ledger/position", headers=acct_auth)
    check("accountant can read the ledger", r.status_code == 200, f"got {r.status_code}")
    r = client.delete(f"/ledger/accounts/{rent_id}", headers={**acct_auth, "X-Confirm-Password": "acct1234"})
    check("accountant cannot delete accounts → 403", r.status_code == 403, f"got {r.status_code}")
    r = client.delete(f"/ledger/accounts/{rent_id}", headers=pwd_h)
    check("admin deletes an unused account → 204", r.status_code == 204, f"got {r.status_code}")

    # ----- ROUTING ENGINE (phase 4) -----
    section("Routing engine")

    taka_id = next(i["id"] for i in client.get("/items", headers=auth).json() if i["abbreviation"] == "TK")
    r = client.post("/designs", headers=auth, json={"item_id": taka_id, "customer_id": cust["id"]})
    check("mint a design → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    design = r.json()
    check(
        "design number takes the item's abbreviation",
        design["design_no"] == "TK-00001",
        design["design_no"],
    )
    d2 = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    check("design numbers count within the item", d2["design_no"] == "TK-00002", d2["design_no"])

    r = client.post(f"/designs/{design['id']}/tag", headers=auth)
    check("generate a tag → 200", r.status_code == 200, f"got {r.status_code}")
    check("tag numbered TAG-YY-NNNNN", r.json()["tag_no"].startswith("TAG-26-"), str(r.json().get("tag_no")))
    r = client.post(f"/designs/{design['id']}/tag", headers=auth)
    check("second tag refused → 409", r.status_code == 409, f"got {r.status_code}")

    # Zahid is a Casting worker on 3.5% agreed wastage (set up in the master
    # data section). Issue him 100g of 22k.
    r = client.post(
        f"/designs/{design['id']}/legs",
        headers=auth,
        json={
            "department_id": casting_id,
            "worker_id": w["id"],
            "gold_issued_g": "100",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "labour_basis": "per_gram",
            "labour_rate": "150",
        },
    )
    check("issue to casting → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    leg = r.json()
    check(
        "agreed wastage snapshotted onto the leg at issue",
        Decimal(str(leg["wastage_allowed_pct"])) == Decimal("3.5"),
        str(leg.get("wastage_allowed_pct")),
    )
    r = client.get(f"/designs/{design['id']}", headers=auth)
    check("design now sits in casting", r.json()["current_department_id"] == casting_id)

    # One pair of hands at a time.
    r = client.post(
        f"/designs/{design['id']}/legs",
        headers=auth,
        json={
            "department_id": casting_id, "worker_id": w["id"], "gold_issued_g": "5",
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("second open leg refused → 409", r.status_code == 409, f"got {r.status_code}")

    # A worker from the wrong department must be refused.
    polish_dept_id = next(d_["id"] for d_ in depts if d_["code"] == "POL")
    r = client.post(
        f"/designs/{d2['id']}/legs",
        headers=auth,
        json={
            "department_id": polish_dept_id, "worker_id": w["id"], "gold_issued_g": "5",
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("worker from another department refused → 400", r.status_code == 400, f"got {r.status_code}")

    # --- the settlement that matters ---
    # 100g out, 94g back. Actual loss 6g; allowed 3.5g; so 2.5g is Zahid's.
    def worker_gold(worker_id: int) -> Decimal:
        return Decimal(
            str(
                client.get(
                    "/ledger/statement",
                    headers=auth,
                    params={
                        "account_code": "1160",
                        "party_type": "worker",
                        "party_id": worker_id,
                        "commodity": "GOLD",
                    },
                ).json()["closing_balance"]
            )
        )

    # While the metal is out, the whole issued amount sits against him.
    check(
        "issued metal shows as a claim on the worker while it is out",
        worker_gold(w["id"]) == Decimal("12.5") + Decimal("91.6667"),
        f"got {worker_gold(w['id'])}, expected 104.1667",
    )
    r = client.post(f"/designs/legs/{leg['id']}/receive", headers=auth, json={"gold_received_g": "94"})
    check("receive from casting → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    settled = r.json()
    check(
        "actual wastage = issued - received",
        Decimal(str(settled["wastage_actual_g"])) == Decimal("6"),
        str(settled["wastage_actual_g"]),
    )
    check(
        "allowed wastage = 3.5% of issued",
        Decimal(str(settled["wastage_allowed_g"])) == Decimal("3.5"),
        str(settled["wastage_allowed_g"]),
    )
    check(
        "only the excess beyond the allowance is the worker's",
        Decimal(str(settled["wastage_excess_g"])) == Decimal("2.5"),
        f"got {settled['wastage_excess_g']}, expected 2.5",
    )
    check(
        "labour charged on delivered weight, not issued",
        Decimal(str(settled["labour_amount"])) == Decimal("94") * Decimal("150"),
        str(settled["labour_amount"]),
    )

    # Once the piece is back, the claim collapses to just the excess: his 12.5g
    # opening plus 2.5g at 22k (2.2917 fine). If the shop were charging the whole
    # 6g difference this would read 12.5 + 5.5 instead.
    check(
        "after receive the worker owes only the excess, not the whole difference",
        abs(worker_gold(w["id"]) - Decimal("14.7917")) <= Decimal("0.0002"),
        f"got {worker_gold(w['id'])}, expected 14.7917 (12.5 opening + 2.2917 excess)",
    )
    check(
        "labour accrued to the worker as a payable",
        Decimal(
            str(
                client.get(
                    "/ledger/statement",
                    headers=auth,
                    params={"account_code": "2120", "party_type": "worker", "party_id": w["id"]},
                ).json()["closing_balance"]
            )
        )
        == Decimal("-14100"),
        "workers payable should be a credit balance of 14,100",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books still balance after a leg round trip", r.json()["balanced"] is True)

    r = client.post(f"/designs/legs/{leg['id']}/receive", headers=auth, json={"gold_received_g": "94"})
    check("receiving a leg twice refused → 409", r.status_code == 409, f"got {r.status_code}")

    # --- a heavier return is legitimate, not an error ---
    # The polisher was created before departments existed on workers, so give
    # him one — the routing engine refuses a worker from the wrong department.
    client.patch(f"/vendors/{polisher['id']}", headers=auth, json={"department_id": polish_dept_id})
    r = client.post(
        f"/designs/{design['id']}/legs",
        headers=auth,
        json={
            "department_id": polish_dept_id,
            "worker_id": polisher["id"],
            "gold_issued_g": "94",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "labour_basis": "flat",
            "labour_rate": "500",
        },
    )
    check("issue to polish → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    polish_leg = r.json()
    r = client.post(
        f"/designs/legs/{polish_leg['id']}/receive", headers=auth, json={"gold_received_g": "95"}
    )
    check("a heavier return is accepted → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    check(
        "weight gain recorded as negative wastage, not a shortfall",
        Decimal(str(r.json()["wastage_actual_g"])) == Decimal("-1"),
        str(r.json()["wastage_actual_g"]),
    )
    check(
        "nothing charged to the worker on a gain",
        Decimal(str(r.json()["wastage_excess_g"])) == Decimal("0"),
        str(r.json()["wastage_excess_g"]),
    )
    check(
        "flat labour ignores weight",
        Decimal(str(r.json()["labour_amount"])) == Decimal("500"),
        str(r.json()["labour_amount"]),
    )

    # --- traceability: the screen the shop lives in ---
    r = client.get(f"/designs/{design['id']}/trace", headers=auth)
    check("trace returns the whole route", r.status_code == 200, f"got {r.status_code}")
    trace = r.json()
    hops = trace.get("hops", [])
    check(
        "trace lists both hops in order",
        len(hops) == 2
        and hops[0]["department"] == "Casting"
        and hops[1]["department"] == "Polish",
        str([h.get("department") for h in hops]),
    )
    check(
        "trace totals roll up the wastage actually charged",
        Decimal(str(trace["totals"]["wastage_excess_g"])) == Decimal("2.5"),
        str(trace.get("totals")),
    )

    # --- cancelling a leg must not forgive the metal ---
    before_issue = worker_gold(w["id"])
    r = client.post(
        f"/designs/{d2['id']}/legs",
        headers=auth,
        json={
            "department_id": casting_id, "worker_id": w["id"], "gold_issued_g": "20",
            "gold_issued_purity": 22, "gold_source_inventory_id": raw_gold["id"],
        },
    )
    cancel_leg_id = r.json()["id"]
    # Cancelling writes off metal, so it is password-confirmed and cannot
    # recover more than went out. Both guards moved here from the retired
    # manufacturing module's cancel, which enforced the same two rules.
    r = client.post(
        f"/designs/legs/{cancel_leg_id}/cancel",
        headers=auth,
        json={"gold_recovered_g": "12", "reason": "no password"},
    )
    check("cancel a leg without password → 401", r.status_code == 401, f"got {r.status_code}")
    r = client.post(
        f"/designs/legs/{cancel_leg_id}/cancel",
        headers=pwd_h,
        json={"gold_recovered_g": "999", "reason": "over-recovery"},
    )
    check(
        "recovering more metal than was issued → 400",
        r.status_code == 400,
        f"got {r.status_code} — inventing metal on a cancel is how stock drifts up",
    )
    r = client.post(
        f"/designs/legs/{cancel_leg_id}/cancel",
        headers=pwd_h,
        json={"gold_recovered_g": "12", "reason": "worker left, recovered 12g of 20g"},
    )
    check("cancel a leg → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    # 20g went out, 12g came back. The 8g the shop never saw again must stay
    # against him — forgiving it on cancel is the hole this rewrite closes.
    # The issue debit is reversed in full, so the net movement is the 8g at 22k.
    unrecovered_fine = (Decimal("8") * Decimal("22") / Decimal("24")).quantize(Decimal("0.0001"))
    check(
        "unrecovered metal stays outstanding against the worker after a cancel",
        abs((worker_gold(w["id"]) - before_issue) - unrecovered_fine) <= Decimal("0.0002"),
        f"net movement {worker_gold(w['id']) - before_issue}, expected {unrecovered_fine}",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books still balance after a cancel", r.json()["balanced"] is True)

    # --- RBAC: staff run the floor but never see the books ---
    r = client.get("/designs", headers=staff_auth)
    check("staff can read designs", r.status_code == 200, f"got {r.status_code}")
    r = client.post("/designs", headers=staff_auth, json={"item_id": taka_id})
    check("staff can mint designs → 201", r.status_code == 201, f"got {r.status_code}")

    # ----- SHOP FORMULAS (ratti discount, setting hisaab, lacker) -----
    # The client's own worked examples, kept as the specification.
    section("Shop formulas")

    # --- discount quoted in ratti, against a base of 96 ---
    # 6 ratti  -> weight / 96 * 90
    # 10 ratti -> weight / 96 * 86
    rate_row = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24}).json()
    day_rate = Decimal(str(rate_row["rate_per_g"]))

    def gold_amount_for(ratti: str) -> Decimal:
        inv = client.post(
            "/invoices",
            headers=auth,
            json={
                "customer_id": customer_id,
                "sale_type": "normal",
                "currency": "PKR",
                "items": [{
                    "description": f"Taka, {ratti} ratti discount",
                    "quantity": 1,
                    "gold_weight_g": "10",
                    "gold_purity": 22,
                    "discount_ratti": ratti,
                }],
            },
        )
        assert inv.status_code == 201, inv.text[:300]
        return Decimal(str(inv.json()["items"][0]["gold_amount"]))

    # The billable weight is rounded to the 4 decimals weights are held in
    # *before* it is priced, so an invoice can be recomputed from the weight
    # printed on it. Pricing the unrounded figure would leave the customer's
    # own arithmetic a few rupees off the total, which is the sort of thing
    # that costs an argument at the counter.
    def priced(billable: Decimal) -> Decimal:
        return (billable.quantize(Decimal("0.0001")) * Decimal("22") / Decimal("24") * day_rate).quantize(
            Decimal("0.01")
        )

    expected_none = priced(Decimal("10"))
    expected_6 = priced(Decimal("10") / 96 * 90)
    expected_10 = priced(Decimal("10") / 96 * 86)

    check("no ratti discount prices the full weight", gold_amount_for("0") == expected_none,
          f"got {gold_amount_for('0')}, expected {expected_none}")
    check(
        "6 ratti discount bills 90/96 of the gold",
        gold_amount_for("6") == expected_6,
        f"got {gold_amount_for('6')}, expected {expected_6}",
    )
    check(
        "10 ratti discount bills 86/96 of the gold",
        gold_amount_for("10") == expected_10,
        f"got {gold_amount_for('10')}, expected {expected_10}",
    )
    r = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
            "items": [{"description": "over-discounted", "quantity": 1, "gold_weight_g": "10",
                       "gold_purity": 22, "discount_ratti": "120"}],
        },
    )
    check(
        "a discount beyond the base is refused, never credited back",
        r.status_code in (400, 422)
        or Decimal(str(r.json()["items"][0]["gold_amount"])) == Decimal("0"),
        f"got {r.status_code}: {r.text[:160]}",
    )

    # --- a multi-unit line must bill for every unit ---
    # Stock deduction and the profit report both scale by quantity, so pricing
    # has to as well: billing one piece while shipping three gives two away.
    multi = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
            "items": [{
                "description": "Three identical bangles",
                "quantity": 3,
                "gold_weight_g": "10",
                "gold_purity": 22,
                "labor_amount": "1000",
            }],
        },
    ).json()
    line = multi["items"][0]
    check(
        "gold on a 3-unit line is priced for 3 units",
        Decimal(str(line["gold_amount"])) == (expected_none * 3),
        f"got {line['gold_amount']}, expected {expected_none * 3}",
    )
    check(
        "labour on a 3-unit line is priced for 3 units",
        Decimal(str(line["line_total"])) == (expected_none * 3) + Decimal("3000"),
        f"got {line['line_total']}, expected {(expected_none * 3) + Decimal('3000')}",
    )

    # --- setting: waste per 100 stones, and a charge per stone ---
    # 0.400 g per 100 over 350 stones = 1.400 g allowed; 350 x Rs 5 = Rs 1,750.
    setting_dept_id = next(d_["id"] for d_ in depts if d_["code"] == "SET")
    setter = client.post(
        "/vendors",
        headers=auth,
        json={"name": "Setting Ustaad", "type": "stone_fixer", "department_id": setting_dept_id},
    ).json()
    set_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{set_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id,
            "worker_id": setter["id"],
            "gold_issued_g": "50",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "piece_count": 350,
            "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
            "labour_basis": "per_piece",
            "labour_rate": "5",
        },
    )
    check("issue a setting leg for 350 stones → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    set_leg = r.json()
    check("piece count recorded on the leg", set_leg["piece_count"] == 350, str(set_leg.get("piece_count")))

    # Lose 2g against a 1.4g allowance: 0.6g is the setter's.
    r = client.post(
        f"/designs/legs/{set_leg['id']}/receive", headers=auth, json={"gold_received_g": "48"}
    )
    check("receive the setting leg → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    settled_set = r.json()
    check(
        "allowance is 0.400g per 100 over 350 stones = 1.400g",
        Decimal(str(settled_set["wastage_allowed_g"])) == Decimal("1.4"),
        f"got {settled_set['wastage_allowed_g']}, expected 1.4000",
    )
    check(
        "excess beyond the per-100 allowance is the setter's",
        Decimal(str(settled_set["wastage_excess_g"])) == Decimal("0.6"),
        f"got {settled_set['wastage_excess_g']}, expected 0.6000",
    )
    check(
        "stone setting charged per stone: 350 x Rs 5",
        Decimal(str(settled_set["labour_amount"])) == Decimal("1750"),
        f"got {settled_set['labour_amount']}, expected 1750.00",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books balance after a per-100 settlement", r.json()["balanced"] is True)

    # --- lacker: weight out, weight in, difference, charge per item ---
    r = client.post(
        "/departments",
        headers=auth,
        json={"name": "Lacker", "code": "LAC", "sequence": 85, "default_rate_per_piece": "500"},
    )
    check("create the lacker department → 201", r.status_code == 201, f"got {r.status_code}")
    lac_dept = r.json()
    lacquerer = client.post(
        "/vendors",
        headers=auth,
        json={"name": "Coating Wala", "type": "other", "department_id": lac_dept["id"]},
    ).json()
    r = client.post(
        f"/designs/{set_design['id']}/legs",
        headers=auth,
        json={
            "department_id": lac_dept["id"],
            "worker_id": lacquerer["id"],
            "gold_issued_g": "48",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "piece_count": 12,
            "labour_basis": "per_piece",
            "labour_rate": "500",
        },
    )
    check("issue a lacker leg → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    lac_leg = r.json()
    r = client.post(
        f"/designs/legs/{lac_leg['id']}/receive", headers=auth, json={"gold_received_g": "48.2"}
    )
    check("receive the lacker leg → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    lac = r.json()
    check(
        "coating added weight — recorded as a gain, not a shortfall",
        Decimal(str(lac["wastage_actual_g"])) == Decimal("-0.2")
        and Decimal(str(lac["wastage_excess_g"])) == Decimal("0"),
        f"actual={lac['wastage_actual_g']} excess={lac['wastage_excess_g']}",
    )
    check(
        "lacker charged per item: 12 x Rs 500",
        Decimal(str(lac["labour_amount"])) == Decimal("6000"),
        f"got {lac['labour_amount']}, expected 6000.00",
    )

    # A per-100 leg with no piece count would silently allow nothing and charge
    # the worker the entire loss.
    guard_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{guard_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"], "gold_issued_g": "10",
            "gold_source_inventory_id": raw_gold["id"], "piece_count": 0,
            "wastage_basis": "per_100_pieces", "wastage_per_100_pcs_g": "0.400",
        },
    )
    check(
        "per-100 leg without a piece count is refused → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:160]}",
    )

    # ----- AI INSIGHTS (degrade-without-a-provider contract) -----
    section("AI insights")
    r = client.get("/insights/wastage-anomalies", headers=auth, params={"days": 90})
    check(
        "wastage analysis returns figures with no model configured",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    r = client.get("/insights/margin-watch", headers=auth, params={"days": 90})
    check(
        "margin watch returns figures with no model configured",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    r = client.post("/insights/ask", headers=auth, json={"question": "kitna sona Zahid ke paas hai"})
    check(
        "ask returns a clean 503 when no model is configured",
        r.status_code == 503,
        f"got {r.status_code}: {r.text[:200]}",
    )
    r = client.get("/insights/wastage-anomalies", headers=staff_auth, params={"days": 90})
    check("staff cannot read the wastage analysis → 403", r.status_code == 403, f"got {r.status_code}")

    # ----- THE MONEY PATH: stock a piece, sell it, settle it, buy metal back -----
    section("Stock, settle, purchase")

    def cash_in_hand() -> Decimal:
        return Decimal(str(client.get("/ledger/position", headers=auth).json()["cash_in_hand"]))

    def gold_in_hand() -> Decimal:
        return Decimal(str(client.get("/ledger/position", headers=auth).json()["gold_in_hand_g"]))

    # --- stock the design that came off the workshop floor ---
    r = client.get(f"/stocking/designs/{set_design['id']}/preview", headers=auth)
    check("stock preview → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    preview = r.json()
    check(
        "preview rolls up labour from every leg",
        Decimal(str(preview["totals"]["labour_total"])) == Decimal("1750") + Decimal("6000"),
        f"got {preview['totals'].get('labour_total')}, expected 7750 (setting 1750 + lacker 6000)",
    )

    r = client.post(
        f"/stocking/designs/{set_design['id']}/stock",
        headers=pwd_h,
        json={
            "name": "Setting Taka",
            "category": "taka",
            "gross_weight_g": "48.2",
            "gold_weight_g": "48.2",
            "gold_purity": 22,
            "other_charges": "250",
            "finished_inventory_location": "showroom",
        },
    )
    check("stock the design → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    stocked = r.json()
    stocked_product_id = stocked.get("product_id") or stocked.get("product", {}).get("id")
    check("stocking produced a product", stocked_product_id is not None, str(stocked)[:200])
    prod = client.get(f"/products/{stocked_product_id}", headers=auth).json()
    check(
        "making cost = every leg's labour plus other charges",
        Decimal(str(prod["total_cost"])) == Decimal("8000"),
        f"got {prod['total_cost']}, expected 8000 (7750 labour + 250 other)",
    )
    check(
        "the piece knows which design it came off",
        prod.get("design_id") == set_design["id"],
        f"got {prod.get('design_id')}",
    )
    r = client.get(f"/designs/{set_design['id']}", headers=auth)
    check("design is now stocked", r.json()["status"] == "stocked", r.json()["status"])
    r = client.post(
        f"/stocking/designs/{set_design['id']}/stock",
        headers=pwd_h,
        json={"name": "Stocked twice", "gross_weight_g": "48.2", "gold_weight_g": "48.2", "gold_purity": 22},
    )
    check("stocking the same design twice refused → 409", r.status_code == 409, f"got {r.status_code}: {r.text[:160]}")
    check("books balance after stocking", client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    def finished_goods_g() -> Decimal:
        st = client.get(
            "/ledger/statement", headers=auth, params={"account_code": "1150", "commodity": "GOLD"}
        ).json()
        return Decimal(str(st["closing_balance"]))

    # The two assertions that used to hang off the manufacturing module land
    # here instead, because this is now where a piece gets finished and stocked.
    acts = {row["action"] for row in client.get("/audit-log", headers=auth).json()}
    check(
        "stocking a finished piece is recorded in the audit log",
        "design.stock" in acts,
        f"actions={sorted(acts)}",
    )
    lr2 = client.get("/reports/manufacturing-loss", headers=auth).json()
    check(
        "the loss report aggregates the bench once legs have run",
        Decimal(str(lr2["overall_actual_loss_g"])) > 0 and lr2["legs"] > 0,
        f"{lr2['legs']} legs, {lr2['overall_actual_loss_g']}g lost",
    )

    fg_after_stock = finished_goods_g()
    check(
        "stocking moves the metal into Finished Goods",
        fg_after_stock > 0,
        f"1150 holds {fg_after_stock} fine g",
    )
    # Raw gold must not still hold the same metal — the piece is on the shelf.
    raw_now = Decimal(
        str(client.get(f"/inventory/{raw_gold['id']}", headers=auth).json()["weight_g"])
    )
    check(
        "the metal is not counted in raw gold and finished goods at once",
        raw_now >= 0,
        f"raw gold {raw_now}g",
    )

    # --- sell it, with wastage marked up and a ratti discount given back ---
    sale = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": cust["id"],
            "sale_type": "normal",
            "currency": "PKR",
            "bill_book_no": "BB-4471",
            # Bill the weight the piece actually holds. A line that bills a
            # different weight from the product it points at is legal but
            # incoherent, and the margin report correctly reports the whole
            # difference as unattributable — which is right, and which would
            # make every margin figure on the dev database look broken.
            "items": [{
                "product_id": stocked_product_id,
                "description": "Setting Taka",
                "quantity": 1,
                "gold_weight_g": "48.2",
                "gold_purity": 22,
                "sale_wastage_pct": "10",
                "discount_ratti": "6",
            }],
        },
    )
    check("create the sale → 201", sale.status_code == 201, f"got {sale.status_code}: {sale.text[:250]}")
    sale = sale.json()
    # 48.2g +10% wastage = 53.02g, then 6 ratti off = 53.02 * 90/96 = 49.7063g.
    billable = (Decimal("48.2") * Decimal("1.10") / 96 * 90).quantize(Decimal("0.0001"))
    check(
        "wastage marks up and ratti discounts down, in that order",
        Decimal(str(sale["items"][0]["gold_amount"]))
        == (billable * Decimal("22") / Decimal("24") * day_rate).quantize(Decimal("0.01")),
        f"got {sale['items'][0]['gold_amount']} — expected pricing on {billable} g",
    )
    check("bill book number kept for reconciliation", sale["bill_book_no"] == "BB-4471")

    r = client.post(f"/invoices/{sale['id']}/issue", headers=pwd_h)
    check("issue the sale → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    issued = r.json()
    total_due = Decimal(str(issued["total"]))
    # Only pieces that went through the stock form were ever debited to 1150.
    # Relieving anything else drives it negative, which is the books claiming
    # the shop shipped stock it never held.
    check(
        "Finished Goods never goes negative",
        finished_goods_g() >= 0,
        f"1150 holds {finished_goods_g()} fine g — a negative balance means a piece was "
        "relieved that was never stocked",
    )
    check(
        "selling relieves Finished Goods — the shelf does not grow forever",
        finished_goods_g() < fg_after_stock,
        f"1150 was {fg_after_stock}, now {finished_goods_g()} — a sale must take the piece off it",
    )
    check(
        "issuing puts the whole bill on the customer's account",
        Decimal(str(issued.get("balance_due", 0))) == total_due,
        f"balance_due {issued.get('balance_due')} vs total {total_due}",
    )

    # --- settle: part cash, the rest in old gold across the counter ---
    cash_before_pay = cash_in_hand()
    part = (total_due / 2).quantize(Decimal("0.01"))
    r = client.post(
        "/payments",
        headers=auth,
        json={
            "customer_id": cust["id"], "invoice_id": sale["id"],
            "method": "cash", "amount": str(part),
        },
    )
    check("take a part cash payment → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    check(
        "cash in hand rises by exactly what was taken",
        cash_in_hand() - cash_before_pay == part,
        f"moved {cash_in_hand() - cash_before_pay}, expected {part}",
    )
    inv_now = client.get(f"/invoices/{sale['id']}", headers=auth).json()
    check(
        "balance due falls by the payment",
        Decimal(str(inv_now["balance_due"])) == (total_due - part),
        f"got {inv_now['balance_due']}, expected {total_due - part}",
    )

    gold_before_ex = gold_in_hand()
    r = client.post(
        "/payments",
        headers=auth,
        json={
            "customer_id": cust["id"], "invoice_id": sale["id"],
            "method": "gold_exchange",
            "gold_weight_g": "5", "gold_purity": 22, "gold_rate_per_g": str(day_rate),
        },
    )
    check("take old gold in exchange → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    exchange = r.json()
    # 5g of 22k is 4.5833 fine grams — the metal must not be banked as pure.
    check(
        "exchanged gold enters stock in fine grams",
        abs((gold_in_hand() - gold_before_ex) - Decimal("4.5833")) <= Decimal("0.0002"),
        f"moved {gold_in_hand() - gold_before_ex}, expected 4.5833",
    )
    check(
        "the exchange is valued at the agreed rate, server-side",
        Decimal(str(exchange["amount"])) == (Decimal("4.5833") * day_rate).quantize(Decimal("0.01")),
        f"got {exchange['amount']}",
    )
    check("books balance after settlement", client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # A reversal must be a contra entry, never a deleted row.
    r = client.post(f"/payments/{exchange['id']}/reverse", headers=pwd_h, json={"reason": "keyed twice"})
    check("reverse a payment → 200", r.status_code in (200, 201), f"got {r.status_code}: {r.text[:220]}")
    check(
        "the reversed payment row still exists",
        client.get(f"/payments?invoice_id={sale['id']}", headers=auth).status_code == 200,
    )
    check(
        "reversing puts the metal back out of stock",
        abs((gold_in_hand() - gold_before_ex)) <= Decimal("0.0002"),
        f"gold still {gold_in_hand() - gold_before_ex} above pre-exchange",
    )
    check("books balance after the reversal", client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # --- buy metal back over the counter ---
    cash_before_buy = cash_in_hand()
    gold_before_buy = gold_in_hand()
    buy_rate = (day_rate * Decimal("0.95") * Decimal("22") / Decimal("24")).quantize(Decimal("0.0001"))
    r = client.post(
        "/purchasing/old-gold",
        headers=auth,
        json={
            "customer_id": cust["id"], "kind": "used",
            "weight_g": "20", "purity": 22, "rate_per_g": str(buy_rate),
        },
    )
    check("buy old gold → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    buy = r.json()
    check(
        "old gold enters stock in fine grams",
        abs((gold_in_hand() - gold_before_buy) - Decimal("18.3333")) <= Decimal("0.0002"),
        f"moved {gold_in_hand() - gold_before_buy}, expected 18.3333",
    )
    check(
        "cash goes out at the shop's buying rate, not the market rate",
        cash_before_buy - cash_in_hand() == Decimal(str(buy["amount"]))
        and Decimal(str(buy["amount"])) < (Decimal("18.3333") * day_rate),
        f"paid {buy['amount']}; the spread below market is the margin",
    )
    check("books balance after buying metal", client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # --- buy stones from a party, then see them in the stock report ---
    supplier = client.post(
        "/purchasing/suppliers", headers=auth, json={"name": "Hanif Jeweller", "phone": "03001112222"}
    )
    check("create a supplier → 201", supplier.status_code == 201, f"got {supplier.status_code}: {supplier.text[:200]}")
    supplier = supplier.json()
    diamond_id = next(
        s_["id"] for s_ in client.get("/stones", headers=auth).json() if s_["name"] == "12 PTR"
    )
    r = client.post(
        "/purchasing/stone-purchases",
        headers=auth,
        json={
            "supplier_id": supplier["id"],
            "extra_cost_pct": "2",
            "items": [{
                "stone_id": diamond_id, "quantity": 100, "weight_ct": "25",
                "rate_per_ct": "4000", "quality": "Commercial", "cut": "Round", "clarity": "VS1",
            }],
        },
    )
    check("buy a stone lot → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    lot = r.json()
    check(
        "the supplier's loading is applied on top of the lines",
        Decimal(str(lot["total"])) == Decimal("102000.00"),
        f"got {lot['total']}, expected 100000 + 2%",
    )
    r = client.get("/purchasing/stone-stock", headers=auth)
    check("stone stock report → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    rows_ = r.json().get("rows", [])
    d12 = next((x for x in rows_ if x.get("stone_id") == diamond_id), None)
    check(
        "the lot shows as purchased",
        d12 and Decimal(str(d12["purchased_weight_ct"])) == Decimal("25"),
        str(d12),
    )
    check(
        "available = purchased less what setting consumed",
        d12
        and Decimal(str(d12["available_weight_ct"]))
        == Decimal(str(d12["purchased_weight_ct"])) - Decimal(str(d12["used_weight_ct"])),
        str(d12),
    )
    check("books balance after buying stones", client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # --- a settlement cannot exceed what is owed ---
    inv_now = client.get(f"/invoices/{sale['id']}", headers=auth).json()
    still_owed = Decimal(str(inv_now["balance_due"]))
    r = client.post(
        "/payments",
        headers=auth,
        json={
            "customer_id": cust["id"], "invoice_id": sale["id"],
            "method": "cash", "amount": str(still_owed + Decimal("1000")),
        },
    )
    check(
        "overpaying a bill is refused rather than driving the balance negative",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:200]}",
    )
    r = client.post(
        "/payments",
        headers=auth,
        json={
            "customer_id": cust["id"], "invoice_id": sale["id"],
            "method": "cash", "amount": str(still_owed),
        },
    )
    check("settling exactly the balance is fine → 201", r.status_code == 201, f"got {r.status_code}")
    check(
        "the bill reads paid once nothing is outstanding",
        client.get(f"/invoices/{sale['id']}", headers=auth).json()["status"] == "paid",
    )

    # --- stones on a cancelled leg were never consumed ---
    avail_before = Decimal(
        str(
            next(
                x for x in client.get("/purchasing/stone-stock", headers=auth).json()["rows"]
                if x["stone_id"] == diamond_id
            )["available_weight_ct"]
        )
    )
    cd = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{cd['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "5", "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "piece_count": 10, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
            "stone_source_inventory_id": raw_stones["id"],
            "stones": [{"stone_id": diamond_id, "quantity_issued": 10, "weight_issued_ct": "2", "rate_per_ct": "4000"}],
        },
    )
    check("issue a setting leg carrying stones → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:220]}")
    stone_leg = r.json()
    r = client.post(
        f"/designs/legs/{stone_leg['id']}/cancel",
        headers=pwd_h,
        json={"gold_recovered_g": "5", "stones_recovered_ct": "2", "reason": "job pulled"},
    )
    check("cancel the leg → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    avail_after = Decimal(
        str(
            next(
                x for x in client.get("/purchasing/stone-stock", headers=auth).json()["rows"]
                if x["stone_id"] == diamond_id
            )["available_weight_ct"]
        )
    )
    check(
        "a cancelled leg consumed no stones — they are back on the shelf",
        avail_after == avail_before,
        f"available went {avail_before} -> {avail_after}; a cancelled leg must not read as consumption",
    )

    # ----- REPORTS (phase 7) -----
    section("Reports")

    m = client.get("/reports/margin", headers=auth, params={"date_from": "2020-01-01", "date_to": "2030-01-01"})
    check("margin report → 200", m.status_code == 200, f"got {m.status_code}: {m.text[:200]}")
    total = m.json()["total"]

    # The decomposition must reconcile. Everything the shop earned, less
    # everything it gave away, has to equal the gross profit — otherwise a lever
    # is being mis-attributed and the owner is reading a story that isn't true.
    attributed = (
        Decimal(str(total["rate_spread"]))
        + Decimal(str(total["wastage_charged"]))
        + Decimal(str(total["making_charges"]))
        + Decimal(str(total["stone_margin"]))
        + Decimal(str(total["uncosted_metal"]))
        - Decimal(str(total["ratti_discount"]))
        - Decimal(str(total["cash_discount"]))
        - Decimal(str(total["round_off"]))
        - Decimal(str(total["making_cost"]))
    )
    check(
        "the levers add up to gross profit",
        abs(attributed - Decimal(str(total["gross_profit"]))) <= Decimal("0.05") * max(total["lines"], 1),
        f"levers {attributed} vs gross {total['gross_profit']}",
    )
    check(
        "wastage charged to customers is reported as its own lever",
        Decimal(str(total["wastage_charged"])) > 0,
        "the sale carried 10% wastage, so it must show as margin from wastage",
    )
    check(
        "the ratti discount is reported as a giveaway, not netted away",
        Decimal(str(total["ratti_discount"])) > 0,
        "6 ratti was given on the sale",
    )
    check(
        "metal sold with no recorded cost is named, not buried in a residual",
        Decimal(str(total["uncosted_metal"])) > 0 and any("no matching recorded cost" in n for n in total["notes"]),
        f"uncosted {total['uncosted_metal']}, notes {total['notes']}",
    )

    # Margin and the older profit report must agree, or two screens tell the
    # owner two different numbers for the same month.
    pr = client.get("/reports/profit", headers=auth).json()
    pkr = next((c for c in pr["by_currency"] if c["currency"] == "PKR"), None)
    check(
        "margin and profit reports agree on the same window",
        pkr and Decimal(str(pkr["profit"])) == Decimal(str(total["gross_profit"])),
        f"profit {pkr and pkr['profit']} vs margin {total['gross_profit']}",
    )

    r = client.get("/reports/manufacturing-loss", headers=auth)
    loss = r.json()
    check(
        "the loss report sees the routing engine, not just the retired model",
        r.status_code == 200 and loss["legs"] > 0 and Decimal(str(loss["overall_excess_g"])) > 0,
        f"legs={loss.get('legs')} excess={loss.get('overall_excess_g')} — it read manufacturing_jobs before",
    )

    r = client.get("/reports/worker-performance", headers=auth, params={"days": 90})
    check("worker performance → 200", r.status_code == 200, f"got {r.status_code}")
    zahid = next((w for w in r.json()["rows"] if w["worker_name"] == "Zahid Bhai"), None)
    check(
        "a worker's outstanding metal comes off the ledger",
        zahid and Decimal(str(zahid["gold_balance_fine_g"])) > 0,
        f"{zahid and zahid['gold_balance_fine_g']} fine g — read from journal lines, not a column",
    )

    for path in ("margin", "worker-performance", "item-performance", "department-throughput", "gold-movement"):
        r = client.get(f"/reports/{path}", headers=auth, params={"format": "csv"})
        check(
            f"{path} exports CSV",
            r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""),
            f"got {r.status_code} {r.headers.get('content-type')}",
        )

    r = client.get("/reports/margin", headers=staff_auth)
    check("staff cannot read the margin report → 403", r.status_code == 403, f"got {r.status_code}")

    # ----- MULTI-CURRENCY: a dollar bill, end to end -----
    section("Multi-currency")

    # Without a rate on record, a dollar bill can be priced but must refuse to
    # post. Guessing one produces books that balance and are wrong by the whole
    # exchange rate, with nothing to show that it happened.
    usd_inv = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": cust["id"], "sale_type": "normal", "currency": "USD",
            "gold_rate_per_g": "400",
            "items": [{"description": "Export bangle", "quantity": 1,
                       "gold_weight_g": "10", "gold_purity": 22}],
        },
    )
    check("raise a USD invoice → 201", usd_inv.status_code == 201, f"got {usd_inv.status_code}")
    usd_inv = usd_inv.json()
    r = client.post(f"/invoices/{usd_inv['id']}/issue", headers=pwd_h)
    check(
        "a USD bill will not post without an FX rate → 409",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:180]}",
    )

    r = client.post("/gold-rates/fx", headers=auth, json={
        "currency": "PKR", "rate_date": date.today().isoformat(), "pkr_per_unit": "1",
    })
    check("a PKR 'exchange rate' is refused → 422", r.status_code == 422, f"got {r.status_code}")

    r = client.post("/gold-rates/fx", headers=auth, json={
        "currency": "USD", "rate_date": date.today().isoformat(), "pkr_per_unit": "280",
    })
    check("set today's USD rate → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:180]}")
    r = client.post("/gold-rates/fx", headers=auth, json={
        "currency": "USD", "rate_date": "2099-12-31", "pkr_per_unit": "999",
    })
    r = client.get("/gold-rates/fx/current", headers=auth, params={"currency": "USD"})
    check(
        "a forward-dated FX rate is not treated as current",
        Decimal(str(r.json()["pkr_per_unit"])) == Decimal("280"),
        f"got {r.json().get('pkr_per_unit')} — a rate keyed ahead is a plan, not a price",
    )

    r = client.post(f"/invoices/{usd_inv['id']}/issue", headers=pwd_h)
    check("the USD bill posts once a rate exists → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    issued_usd = r.json()
    usd_total = Decimal(str(issued_usd["total"]))
    check(
        "the rate is snapshotted onto the invoice",
        Decimal(str(issued_usd["fx_rate_to_pkr"])) == Decimal("280"),
        f"got {issued_usd.get('fx_rate_to_pkr')}",
    )

    # The customer's account is kept in dollars; the books balance in rupees.
    st = client.get("/ledger/statement", headers=auth, params={
        "account_code": "1210", "party_type": "customer", "party_id": cust["id"], "commodity": "USD",
    }).json()
    check(
        "the receivable is carried in the currency the customer was billed in",
        Decimal(str(st["closing_balance"])) == usd_total,
        f"USD receivable {st['closing_balance']} vs bill {usd_total}",
    )
    check("books still balance with a USD bill on them",
          client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # Settle it in rupees. The bill's own rate converts, so paying exactly what
    # was billed closes the balance instead of leaving rupees of FX drift.
    r = client.post("/payments", headers=auth, json={
        "customer_id": cust["id"], "invoice_id": usd_inv["id"],
        "method": "cash", "currency": "PKR", "amount": str((usd_total * 280).quantize(Decimal("0.01"))),
    })
    check("settle a USD bill in rupees → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    after = client.get(f"/invoices/{usd_inv['id']}", headers=auth).json()
    check(
        "paying the rupee equivalent closes the dollar bill exactly",
        Decimal(str(after["balance_due"])) == Decimal("0.00"),
        f"balance_due {after['balance_due']} — FX drift would leave a residue nobody can explain",
    )
    check("the bill reads paid", after["status"] == "paid", after["status"])
    check("books balance after a cross-currency settlement",
          client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # --- the headline money figures must survive a mixed-currency account ---
    # The dollar bill above debited the receivable in USD and its settlement
    # credited it in PKR. Reading that account one commodity at a time keeps the
    # payment and drops the invoice, so a paid-up book reports the shop owing
    # its customers a seven-figure sum. The trial balance stays perfectly
    # balanced throughout, which is exactly why this needs its own assertion.
    pos = client.get("/ledger/position", headers=auth).json()
    recv = Decimal(str(pos["customer_receivable"]))
    check(
        "the receivable is valued across currencies, not read in one of them",
        recv >= 0,
        f"customer_receivable {recv} — a large negative means the USD leg was dropped",
    )
    cust_pkr = Decimal(str(client.get(
        f"/ledger/statement?account_code=1210&commodity=PKR", headers=auth
    ).json().get("closing_balance", 0)))
    check(
        "and it differs from the PKR-only reading, which is the whole point",
        recv != cust_pkr,
        f"valued {recv} vs PKR-only {cust_pkr}",
    )
    inv_view = client.get(f"/invoices/{usd_inv['id']}", headers=auth).json()
    check(
        "a customer's balance on an invoice is valued the same way",
        Decimal(str(inv_view["customer_balance"])) >= 0,
        f"customer_balance {inv_view['customer_balance']} — a settled dollar bill "
        "must not leave its customer looking heavily in credit",
    )

    # --- a stone priced in dollars must be capitalised in rupees ---
    usd_stone = client.post("/stones", headers=auth, json={
        "name": "Imported Emerald", "kind": "emerald", "category": "stone",
        "default_rate_per_ct": "100", "currency": "USD",
    }).json()
    fx_prod = client.post("/products", headers=auth, json={
        "name": "FX cost probe", "gold_weight_g": "0", "gold_purity": 22,
    }).json()
    before_cost = Decimal(str(fx_prod["material_cost"]))
    r = client.post(f"/products/{fx_prod['id']}/stones", headers=auth, json={
        "stone_id": usd_stone["id"], "quantity": 1, "weight_ct": "2", "rate_per_ct": "100",
    })
    check("attach a USD-priced stone → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    check(
        "the row records the currency it was priced in",
        r.json().get("currency") == "USD",
        f"got {r.json().get('currency')} — a rate without its currency is a number, not a price",
    )
    after = client.get(f"/products/{fx_prod['id']}", headers=auth).json()
    # 2ct at $100 = $200, at 280 = PKR 56,000. Unconverted it would read 200.
    check(
        "a dollar-priced stone is capitalised in rupees, not at its face number",
        Decimal(str(after["material_cost"])) - before_cost == Decimal("56000.00"),
        f"material_cost moved {Decimal(str(after['material_cost'])) - before_cost}, expected 56000.00 "
        "(2ct x $100 x 280) — 200.00 would mean the FX was dropped",
    )

    # ----- INTERNAL INVARIANTS -----
    section("Internal invariants")
    # Colliding advisory-lock keys don't error, they just make unrelated
    # operations queue behind each other under load with nothing to explain it.
    # The registry reserves 7_300_004..006 for the Dev branch's serials; this
    # fails if anything reclaims them. See docs/BRANCH_DIVERGENCE.md.
    from app.core import lock_keys

    try:
        lock_keys.assert_unique()
        check("advisory lock keys are unique and the Dev block is reserved", True)
    except AssertionError as exc:
        check("advisory lock keys are unique and the Dev block is reserved", False, str(exc))

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

    r = client.get("/designs", headers=auth, params={"status": "stocked"})
    check(
        "filter designs by status",
        r.status_code == 200 and all(d["status"] == "stocked" for d in r.json()),
        f"got {r.status_code}",
    )

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
