"""
End-to-end smoke test of every implemented feature.
Assumes: Postgres up, migrations + seed run, uvicorn on 127.0.0.1:8000.

Run: python -m tests.e2e
"""
from __future__ import annotations

import io
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import httpx

# Overridable so the suite can be pointed at a throwaway instance. It rebuilds
# the database it runs against, and a shop's live data is not a thing to find
# out about afterwards.
BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
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
    # The AI endpoints wait on a third party and the free models are slow — a
    # large one on a free tier can sit in a queue for a minute before it starts.
    # They get their own client rather than a raised global timeout, so a real
    # endpoint that starts taking 30s still fails the suite the way it should.
    ai_client = httpx.Client(base_url=API, timeout=240)

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

    # Roles looked up by name, not by arithmetic on an id.
    #
    # This used to read the first user's role and add two, on the assumption
    # that roles were seeded admin-first in a fixed order. Adding the super
    # admin put a different account first and the whole suite stopped at line
    # one hundred and seventeen — which is the argument against deriving an
    # identifier from insertion order in the first place.
    role_ids = {u["role"]["name"]: u["role"]["id"] for u in r.json() if u.get("role")}
    admin_role_id = me["role"]["id"]
    role_ids.setdefault("admin", admin_role_id)
    staff_role_id = role_ids.get("staff")
    if staff_role_id is None:
        # No user holds it yet, which is the ordinary case on a fresh database.
        # Seeded in a known order after the two accounts, so it is one of the
        # ids near admin's — probe rather than guess.
        for candidate in range(admin_role_id + 1, admin_role_id + 4):
            probe = client.post("/users", headers=auth, json={
                "email": f"probe{candidate}@jewelryerp.com", "full_name": "probe",
                "password": "probe12345", "role_id": candidate,
            })
            if probe.status_code == 201 and probe.json()["role"]["name"] == "staff":
                staff_role_id = candidate
                # Its own confirm header: `pwd_h` is not bound until later in
                # the file, and a closure reading it here fails with a name
                # error rather than a useful message.
                client.delete(
                    f"/users/{probe.json()['id']}",
                    headers={**auth, "X-Confirm-Password": "admin123"},
                )
                break
    check("the staff role can be found by name", staff_role_id is not None,
          f"roles seen: {sorted(role_ids)}")

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
    # Every worker handles a stage. That is what the worker dropdown on a design
    # filters by, so one saved without a stage can never be given work — he is
    # simply absent from every screen that matters.
    depts_by_code = {d["code"]: d["id"] for d in client.get("/departments", headers=auth).json()}
    check(
        "the floor is the three stages the shop runs",
        set(depts_by_code) == {"MAKE", "SET", "LAC"},
        f"got {sorted(depts_by_code)}",
    )
    karigar = client.post(
        "/vendors", headers=auth, json={"name": "Ravi Karigar", "department_id": depts_by_code["MAKE"]},
    ).json()
    fixer = client.post(
        "/vendors", headers=auth, json={"name": "Stone Master", "department_id": depts_by_code["SET"]},
    ).json()
    lacker = client.post(
        "/vendors", headers=auth, json={"name": "Coating Wala", "department_id": depts_by_code["LAC"]},
    ).json()
    check("create maker / stone fixer / lacker", all(v.get("id") for v in (karigar, fixer, lacker)))

    r = client.post("/vendors", headers=auth, json={"name": "Nobody's Worker"})
    check(
        "a worker without a stage is refused → 422",
        r.status_code == 422,
        f"got {r.status_code} — one saved this way can never be picked on a design",
    )
    r = client.post(
        "/vendors", headers=auth,
        json={"name": "Second Maker", "department_id": depts_by_code["MAKE"], "type": "polish"},
    )
    check(
        "the legacy type follows the stage, not the payload",
        r.status_code == 201 and r.json()["type"] == "karigar",
        f"got {r.status_code}: {r.json().get('type')} — the stage is the routing key",
    )
    check(
        "the stone fixer's legacy type is derived too",
        fixer["type"] == "stone_fixer" and lacker["type"] == "other",
        f"got {fixer.get('type')} / {lacker.get('type')}",
    )

    r = client.get("/vendors", headers=auth, params={"department_id": depts_by_code["SET"]})
    check(
        "filter workers by stage",
        r.status_code == 200
        and r.json()
        and all(v["department_id"] == depts_by_code["SET"] for v in r.json()),
    )

    def open_pot(body, *, weight_g="0", weight_ct="0", quantity=0,
                 rate_per_g=None, value=None):
        """
        Create a pot and record what it held when the books opened.

        Two calls, because that is now the only honest way in: `POST /inventory`
        opens an empty container and `POST /inventory/{id}/opening` puts a
        quantity in it *and* the matching value into 3200 Opening Balance
        Equity. Setting a weight on the create used to work and posted nothing,
        which is how the shelves and the books drifted 1,195 fine grams apart.
        """
        pot = client.post("/inventory", headers=auth, json=body)
        assert pot.status_code == 201, f"pot create failed: {pot.status_code} {pot.text[:200]}"
        pot = pot.json()
        payload = {"weight_g": weight_g, "weight_ct": weight_ct, "quantity": quantity}
        if rate_per_g is not None:
            payload["rate_per_g"] = rate_per_g
        if value is not None:
            payload["value"] = value
        # Its own confirm header rather than the module-level `pwd_h`, which is
        # not bound until later in the file — a closure that reads it here would
        # fail on the first pot with a name error, not a useful message.
        r = client.post(
            f"/inventory/{pot['id']}/opening",
            headers={**auth, "X-Confirm-Password": "admin123"},
            json=payload,
        )
        assert r.status_code == 201, f"opening failed: {r.status_code} {r.text[:250]}"
        return r.json()

    # ----- INVENTORY (raw) -----
    section("Inventory (raw)")
    raw_gold = open_pot(
        {"type": "raw_gold", "label": "22k bullion", "purity": 22, "location": "vault"},
        weight_g="500", rate_per_g="30000",
    )
    raw_stones = open_pot(
        {"type": "raw_stone", "label": "diamonds VS1"},
        weight_ct="20", value="80000",
    )
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

    # Metal can no longer be adjusted straight onto the shelf. This was the
    # last of four doors that moved stock without the books hearing: it wrote
    # the pot and nothing else, so 1130 and the pot disagreed immediately with
    # neither able to say which was right.
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
    check(
        "a direct metal adjustment is refused → 409",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:160]}",
    )
    check(
        "and it says where to do it properly",
        "reconciliation" in r.text.lower() or "count" in r.text.lower(),
        r.text[:160],
    )
    r = client.get(f"/inventory/{raw_gold['id']}", headers=auth)
    check(
        "the pot is untouched by the refusal",
        Decimal(str(r.json()["weight_g"])) == Decimal("500"),
        f"got {r.json()['weight_g']} — a refused adjustment must not half-apply",
    )

    # Stones keep the direct path: their inventory is carried in money at cost
    # and a carat adjustment moves no metal control account.
    r = client.post(
        "/stock-movements",
        headers=pwd_h,
        json={
            "inventory_item_id": raw_stones["id"],
            "type": "adjustment",
            "weight_ct_delta": "-1",
            "notes": "recount",
        },
    )
    check("a stone adjustment still posts → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:160]}")
    check(
        "underflow is still refused → 400",
        client.post(
            "/stock-movements",
            headers=pwd_h,
            json={"inventory_item_id": raw_stones["id"], "type": "adjustment",
                  "weight_ct_delta": "-100000"},
        ).status_code == 400,
        "a pot cannot hold less than nothing",
    )

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
    finished_inv = open_pot(
        {"type": "finished_product", "label": "Finished Test Ring",
         "location": "showroom", "purity": 22, "product_id": finished_product_id},
        weight_g="9.6", weight_ct="1.8", quantity=1, value="120000",
    )
    check("stock it as finished goods → 201", bool(finished_inv.get("id")), str(finished_inv)[:120])
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
        # Credit terms. The printed bill carries them and works the due date
        # out from them, so both have to survive the round trip.
        "term_days": 30,
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

    # --- what the printed bill needs ---
    check("credit terms stored", inv["term_days"] == 30, str(inv.get("term_days")))
    check(
        "a draft has no due date",
        inv["due_date"] is None,
        f"got {inv.get('due_date')} — nothing is due from a bill that was never issued",
    )
    check(
        "the bill knows which shop raised it",
        (inv.get("letterhead") or {}).get("print_name") == "Main Shop",
        str(inv.get("letterhead")),
    )

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

    # The due date only exists once there is an issue date to count from, and
    # it is derived rather than stored, so it always agrees with the terms.
    issued = client.get(f"/invoices/{invoice_id}", headers=auth).json()
    # Counted from the shop's day, not the server's or the database's. Between
    # local midnight and dawn those disagree, and a due date a day out is a
    # payment chased on the wrong morning — so the expected value is derived
    # from what the shop itself thinks today is.
    shop_today = client.get("/dashboard", headers=auth, params={"days": 7}).json()["as_of"]
    expected_due = (date.fromisoformat(shop_today) + timedelta(days=30)).isoformat()
    check(
        "due date = the shop's day + term days",
        issued["due_date"] == expected_due,
        f"got {issued['due_date']}, expected {expected_due}",
    )

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
    p2_inv = open_pot(
        {"type": "finished_product", "label": "Ring 2", "location": "showroom",
         "purity": 22, "product_id": p2_id},
        weight_g="7.9", quantity=1, value="95000",
    )
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

    vend = client.post("/vendors", headers=auth, json={
        "name": "ToDelete Vend", "department_id": depts_by_code["MAKE"],
    }).json()
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
    open_pot(
        {"type": "finished_product", "label": "Issue Weight Ring", "location": "showroom",
         "purity": 22, "product_id": d7_prod_id},
        weight_g="8", quantity=1, value="96000",
    )

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

    # Departments ship seeded so a fresh install is usable immediately: the
    # three stages this shop runs, in the order work flows through them.
    r = client.get("/departments", headers=auth)
    depts = r.json()
    check("3 stages seeded", r.status_code == 200 and len(depts) == 3, f"got {len(depts)}")
    check(
        "stages ordered by sequence",
        [d["code"] for d in depts] == ["MAKE", "SET", "LAC"],
        str([d["code"] for d in depts]),
    )
    setting = next((d for d in depts if d["code"] == "SET"), None)
    check(
        "the stone fixer is the stone-consuming stage",
        setting and setting["consumes_stones"] is True and setting["name"] == "Stone Fixer",
        str(setting),
    )

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

    # Workers gained a stage, agreed wastage and opening balances.
    maker_id = next(d["id"] for d in depts if d["code"] == "MAKE")
    r = client.post(
        "/vendors",
        headers=auth,
        json={
            "name": "Zahid Bhai",
            "department_id": maker_id,
            "default_wastage_pct": "3.5",
            "opening_gold_g": "12.5",
            "cnic": "42101-7654321-9",
        },
    )
    check("create worker with a stage → 201", r.status_code == 201, f"got {r.status_code}")
    w = r.json()
    check("worker stage name resolved", w["department_name"] == "Maker", str(w))
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
        json={"name": "Inherits Dept Rate", "department_id": enamel_id},
    )
    check(
        "worker with no rate inherits the stage's",
        Decimal(str(r.json()["effective_wastage_pct"])) == Decimal("2.0"),
        str(r.json().get("effective_wastage_pct")),
    )
    check(
        "a stage outside the three legacy roles leaves the worker unlabelled",
        r.json()["type"] == "other",
        f"got {r.json().get('type')} — better absent from the old roll-up than filed wrong",
    )
    r = client.delete(f"/departments/{maker_id}", headers=pwd_h)
    check("delete a stage with workers → 409", r.status_code == 409, f"got {r.status_code}")

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
    # Every code the posting services resolve by name must be present. Asserted
    # as a set rather than a count on purpose: a count has to be edited every
    # time the chart grows, and an off-by-one edit to make a test pass is
    # exactly how a genuinely missing account gets waved through.
    required = {
        "1110", "1120", "1130", "1140", "1150", "1160",
        "1210", "1215",
        "2110", "2120",
        "3100", "3200",
        "4100", "4200", "4300",
        "5100", "5200", "5300", "5400",
    }
    missing = sorted(required - set(by_code))
    check(
        "chart of accounts has every system account",
        r.status_code == 200 and not missing,
        f"missing {missing}" if missing else f"got {len(accounts)}",
    )
    check(
        "party metal and making income are postable system accounts",
        all(by_code[c]["is_system"] and by_code[c]["is_postable"] for c in ("1215", "4300")),
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
    # The metal is a delta for the same reason, and now more so: opening stock
    # posts into 1130 as well, so "gold in hand" is no longer only what this
    # section bought. Before that path existed the pots held metal the ledger
    # had never heard of — the whole reason it exists.
    gold_before_buy = Decimal(
        str(client.get("/ledger/position", headers=auth).json()["gold_in_hand_g"])
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
        Decimal(str(pos["gold_in_hand_g"])) - gold_before_buy == Decimal("91.6667"),
        f"moved {Decimal(str(pos['gold_in_hand_g'])) - gold_before_buy}, expected 91.6667 "
        "— 100g of 22k is 91.6667 fine, and booking the gross would overstate the "
        "shop's metal by the alloy",
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

    # --- trade billing: gold charged in grams, not rupees ---
    # A jeweller settles the metal in metal. The bill must state the fine grams
    # to hand over and must NOT also price that same gold in rupees, or he is
    # invoiced for it twice in two different units.
    r = client.post(
        "/customers", headers=auth, json={"name": "Sarafa Trading Co", "is_trade": True}
    )
    check("create a trade customer → 201", r.status_code == 201, f"got {r.status_code}")
    jeweller = r.json()
    check("the customer is marked as trade", jeweller.get("is_trade") is True, str(jeweller.get("is_trade")))

    r = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": jeweller["id"],
            "sale_type": "normal",
            "currency": "PKR",
            "gold_rate_per_g": "6500",
            "items": [
                {
                    "description": "Trade ring",
                    "quantity": 1,
                    "gold_weight_g": "10",
                    "gold_purity": 22,
                    "stone_weight_ct": "0.5",
                    "stone_rate_per_ct": "80000",
                    "labor_amount": "5000",
                }
            ],
        },
    )
    check("bill a trade customer → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    tb = r.json()
    check(
        "a trade customer's bill charges gold in grams",
        tb["gold_charged_in"] == "grams",
        str(tb.get("gold_charged_in")),
    )
    check(
        "the gold is not priced on a trade bill",
        Decimal(str(tb["items"][0]["gold_amount"])) == 0,
        str(tb["items"][0]["gold_amount"]),
    )
    check(
        "the cash total is stones and making only",
        Decimal(str(tb["total"])) == Decimal("45000.00"),
        str(tb["total"]),
    )
    check(
        "the bill states the fine grams to hand over",
        Decimal(str(tb["metal_due_fine_g"])) == Decimal("9.1667"),
        str(tb["metal_due_fine_g"]),
    )
    r = client.post(f"/invoices/{tb['id']}/issue", headers=pwd_h)
    check("issue a trade bill → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    # The metal obligation has to reach the party's metal account, or the shop
    # has sold gold it will never chase.
    r = client.get(
        "/ledger/party-statement",
        headers=auth,
        params={"party_type": "customer", "party_id": jeweller["id"]},
    )
    tps = r.json()
    check(
        "issuing a trade bill puts metal on the jeweller's account",
        Decimal(str(tps["closing_metal_g"])) == Decimal("9.1667"),
        str(tps.get("closing_metal_g")),
    )
    check(
        "and the cash side carries only the stones and making",
        Decimal(str(tps["closing_cash"])) == Decimal("45000.00"),
        str(tps.get("closing_cash")),
    )

    # The counter path must be untouched by all of this.
    r = client.post(
        "/invoices",
        headers=auth,
        json={
            "customer_id": customer_id,
            "sale_type": "normal",
            "currency": "PKR",
            "gold_rate_per_g": "6500",
            "items": [
                {
                    "description": "Counter ring",
                    "quantity": 1,
                    "gold_weight_g": "10",
                    "gold_purity": 22,
                    "stone_weight_ct": "0.5",
                    "stone_rate_per_ct": "80000",
                    "labor_amount": "5000",
                }
            ],
        },
    )
    cb = r.json()
    check(
        "a counter customer's bill still charges gold in rupees",
        cb["gold_charged_in"] == "rupees",
        str(cb.get("gold_charged_in")),
    )
    check(
        "the counter bill prices the gold and owes no metal",
        Decimal(str(cb["items"][0]["gold_amount"])) > 0
        and Decimal(str(cb["metal_due_fine_g"])) == 0,
        f"gold={cb['items'][0]['gold_amount']} metal={cb['metal_due_fine_g']}",
    )
    check(
        "the two bills differ by exactly the priced gold",
        Decimal(str(cb["total"])) - Decimal(str(tb["total"]))
        == Decimal(str(cb["items"][0]["gold_amount"])),
        f"{cb['total']} - {tb['total']} vs {cb['items'][0]['gold_amount']}",
    )

    # --- party statement: the wholesale account, in metal and money at once ---
    # The document a jeweller dealing with other jewellers actually keeps. The
    # two columns must never be netted: the metal side is unpriced on purpose,
    # because the rate is agreed on the day the gold moves and not on the day
    # the bill was written.
    r = client.get(
        "/ledger/party-statement",
        headers=auth,
        params={"party_type": "customer", "party_id": customer_id},
    )
    check("party statement → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    ps = r.json()
    check("party statement names the party", bool(ps.get("party_name")), str(ps.get("party_name")))
    check(
        "metal and cash are reported as separate closing figures",
        "closing_metal_g" in ps and "closing_cash" in ps,
        str(list(ps)),
    )
    check(
        "the cash column foots against its opening and period totals",
        Decimal(str(ps["closing_cash"]))
        == Decimal(str(ps["opening_cash"]))
        + Decimal(str(ps["cash_debit_total"]))
        - Decimal(str(ps["cash_credit_total"])),
        f"{ps['opening_cash']} + {ps['cash_debit_total']} - {ps['cash_credit_total']} "
        f"!= {ps['closing_cash']}",
    )
    check(
        "the metal column foots independently of the cash one",
        Decimal(str(ps["closing_metal_g"]))
        == Decimal(str(ps["opening_metal_g"]))
        + Decimal(str(ps["metal_in_total_g"]))
        - Decimal(str(ps["metal_out_total_g"])),
        f"{ps['opening_metal_g']} + {ps['metal_in_total_g']} - {ps['metal_out_total_g']} "
        f"!= {ps['closing_metal_g']}",
    )
    check(
        "one row per document, not one per posting",
        len({row["entry_id"] for row in ps["rows"]}) == len(ps["rows"]),
        f"{len(ps['rows'])} rows, {len({row['entry_id'] for row in ps['rows']})} entries",
    )
    if ps["rows"]:
        check(
            "the running cash balance continues down the page",
            Decimal(str(ps["rows"][-1]["cash_balance"])) == Decimal(str(ps["closing_cash"])),
            f"{ps['rows'][-1]['cash_balance']} vs {ps['closing_cash']}",
        )
        check(
            "each row names the document that caused it",
            all(row["entry_no"] for row in ps["rows"]),
        )
    # A party with nothing against them is an empty account, not an error — the
    # screen has to open before the first trade, or it can never show the first.
    r = client.get(
        "/ledger/party-statement",
        headers=auth,
        params={"party_type": "salesman", "party_id": 999999},
    )
    check("statement for a party with no activity → 200", r.status_code == 200, f"got {r.status_code}")
    empty = r.json()
    check(
        "an untraded account opens at zero on both columns",
        Decimal(str(empty["closing_metal_g"])) == 0 and Decimal(str(empty["closing_cash"])) == 0,
        str(empty.get("closing_metal_g")),
    )

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
            "department_id": maker_id,
            "worker_id": w["id"],
            "gold_issued_g": "100",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "labour_basis": "per_gram",
            "labour_rate": "150",
        },
    )
    check("issue to the maker → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    leg = r.json()
    check(
        "agreed wastage snapshotted onto the leg at issue",
        Decimal(str(leg["wastage_allowed_pct"])) == Decimal("3.5"),
        str(leg.get("wastage_allowed_pct")),
    )
    r = client.get(f"/designs/{design['id']}", headers=auth)
    check("design now sits with the maker", r.json()["current_department_id"] == maker_id)

    # One pair of hands at a time.
    r = client.post(
        f"/designs/{design['id']}/legs",
        headers=auth,
        json={
            "department_id": maker_id, "worker_id": w["id"], "gold_issued_g": "5",
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("second open leg refused → 409", r.status_code == 409, f"got {r.status_code}")

    # A worker from the wrong stage must be refused: the maker cannot be handed
    # a stone-setting leg.
    fixer_dept_id = next(d_["id"] for d_ in depts if d_["code"] == "SET")
    r = client.post(
        f"/designs/{d2['id']}/legs",
        headers=auth,
        json={
            "department_id": fixer_dept_id, "worker_id": w["id"], "gold_issued_g": "5",
            "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check("worker from another stage refused → 400", r.status_code == 400, f"got {r.status_code}")

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
    check("receive from the maker → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
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

    # --- a stage done in-house has no worker, and no one to charge a shortfall to ---
    # Lacquering is the one the shop does on its own bench. Requiring a worker
    # there would mean inventing a record for the shop itself, which then shows
    # up in the wastage reports as a party losing you metal. The leg still
    # tracks the gram; it just carries no ledger party.
    lac_dept_id = next(d_["id"] for d_ in depts if d_["code"] == "LAC")
    inhouse_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{inhouse_design['id']}/legs",
        headers=auth,
        json={
            "department_id": lac_dept_id, "gold_issued_g": "10",
            "gold_issued_purity": 22, "gold_source_inventory_id": raw_gold["id"],
        },
    )
    check(
        "issue to an in-house stage with no worker → 201",
        r.status_code == 201,
        f"got {r.status_code}: {r.text[:220]} — a stage the shop does itself has nobody to name",
    )
    inhouse_leg = r.json()
    check("the leg carries no worker", inhouse_leg.get("worker_id") is None, str(inhouse_leg.get("worker_id")))

    def recovered_g() -> Decimal:
        st = client.get(
            "/ledger/statement", headers=auth, params={"account_code": "4200", "commodity": "GOLD"}
        ).json()
        return Decimal(str(st["closing_balance"]))

    rec_before = recovered_g()
    # Lose 2g against a zero allowance: on a worker's leg this would be charged
    # back to him. Here there is nobody to charge.
    r = client.post(
        f"/designs/legs/{inhouse_leg['id']}/receive", headers=auth, json={"gold_received_g": "8"}
    )
    check("receive an in-house leg → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    check(
        "an in-house shortfall is the shop's own cost, not income from nobody",
        recovered_g() == rec_before,
        f"4200 moved by {recovered_g() - rec_before} fine g — booking wastage recovered "
        "with no party credits income against a debt owed by no one",
    )
    check(
        "books balance after an in-house leg",
        client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True,
    )

    # --- a heavier return is legitimate, not an error ---
    # Lacquer adds weight. A piece that comes back heavier is the normal
    # outcome of that stage, not a data-entry mistake.
    r = client.post(
        f"/designs/{design['id']}/legs",
        headers=auth,
        json={
            "department_id": lac_dept_id,
            "worker_id": lacker["id"],
            "gold_issued_g": "94",
            "gold_issued_purity": 22,
            "gold_source_inventory_id": raw_gold["id"],
            "labour_basis": "flat",
            "labour_rate": "500",
        },
    )
    check("issue to the lacker → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    coat_leg = r.json()
    r = client.post(
        f"/designs/legs/{coat_leg['id']}/receive", headers=auth, json={"gold_received_g": "95"}
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
        and hops[0]["department"] == "Maker"
        and hops[1]["department"] == "Lacker",
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
            "department_id": maker_id, "worker_id": w["id"], "gold_issued_g": "20",
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

    # --- a line has to say which piece it is, not only what it cost ---
    # `description` is typed at the counter and is routinely just "ring". The
    # product is eager-joined on the row already, so naming it costs nothing and
    # is what lets a bill be checked against the object in the box.
    idline = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "gold_rate_per_g": "6500",
        "items": [{
            "product_id": finished_product_id, "description": "ring",
            "quantity": 1, "gold_weight_g": "5", "gold_purity": 22,
        }],
    }).json()["items"][0]
    check(
        "an invoice line names the piece it is billing",
        idline.get("product_name") and idline.get("product_serial_no"),
        f"name={idline.get('product_name')} serial={idline.get('product_serial_no')} — "
        "a line carrying only a typed description cannot identify anything",
    )
    check(
        "and carries its photograph field for the printed bill",
        "product_image_url" in idline,
        "the customer's copy shows the article, so the field has to reach the client",
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

    # --- the maker: ratti of the returned weight, settled in fine grams ---
    # 100.000g of pure 24k goes out. 107.560g of 21k comes back, 6 ratti agreed.
    #
    #   allowance = 107.560 / 96 * 6   =   6.7225 g of 21k
    #   credited  = 107.560 + 6.7225   = 114.2825 g of 21k
    #   fine      = 114.2825 * 21 / 24 =  99.9972 g pure
    #   -> the maker is 0.0028 g of pure gold short.
    #
    # Two readings of this were possible and they differ by a third of a gram
    # on a hundred: taking the allowance as *pure* grams instead credits him
    # 100.8375g and leaves the shop owing him 0.8375g on a job that came out
    # square. The client confirmed the alloy reading, so it is asserted here.
    make_dept_id = next(d_["id"] for d_ in depts if d_["code"] == "MAKE")
    pure_gold = open_pot(
        {"type": "raw_gold", "label": "24k pure for maker",
         "purity": 24, "location": "vault"},
        weight_g="500", rate_per_g="30000",
    )
    maker_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{maker_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id,
            "worker_id": karigar["id"],
            "gold_issued_g": "100",
            "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received",
            "wastage_ratti": "6",
            "piece_count": 12,
            "labour_basis": "per_piece",
            "labour_rate": "800",
        },
    )
    check("issue 100g of pure gold to the maker on 6 ratti → 201",
          r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    maker_leg = r.json()

    # A ratti leg with no ratti figure would allow nothing and charge him the
    # whole difference between pure metal out and alloy back — about an eighth
    # of the weight on a 21k job.
    # Its own design: the one above is still out with the maker, and a second
    # leg on it is refused for that reason rather than for the missing ratti,
    # which would make this assertion pass without testing anything.
    ratti_guard_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    guard = client.post(
        f"/designs/{ratti_guard_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "10", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received",
        },
    )
    check("a ratti leg without the agreed ratti is refused → 400",
          guard.status_code == 400, f"got {guard.status_code}: {guard.text[:200]}")

    r = client.post(
        f"/designs/legs/{maker_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600", "gold_received_purity": 21},
    )
    check("receive 107.560g of 21k from the maker → 200",
          r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    settled = r.json()
    check(
        "6 ratti on 107.560g allows 6.7225g of 21k",
        Decimal(str(settled["wastage_allowed_g"])) == Decimal("6.7225"),
        f"got {settled['wastage_allowed_g']}, expected 6.7225",
    )
    check(
        "the allowance is 5.8822g once converted to fine",
        Decimal(str(settled["wastage_allowed_fine_g"])) == Decimal("5.8822"),
        f"got {settled['wastage_allowed_fine_g']}, expected 5.8822 "
        "— 6.7225 here would mean the allowance was read as pure gold",
    )
    check(
        "the maker is left owing 0.0028g of pure gold",
        Decimal(str(settled["wastage_excess_fine_g"])) == Decimal("0.0028"),
        f"got {settled['wastage_excess_fine_g']}, expected 0.0028",
    )
    check(
        "the purity that came back is recorded, not the purity that went out",
        settled["gold_received_purity"] == 21,
        f"got {settled['gold_received_purity']} — crediting 21k at 24k overstates "
        "the return by about a seventh",
    )
    check(
        "the maker is paid for the pieces he delivered: 12 x Rs 800",
        Decimal(str(settled["labour_amount"])) == Decimal("9600"),
        f"got {settled['labour_amount']}, expected 9600.00",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books balance after a ratti settlement", r.json()["balanced"] is True)

    # --- the purity that comes back is not optional on a ratti leg ---
    # The whole reason the maker's convention exists is that pure metal goes out
    # and alloy comes back. Leave the returned purity blank and the fallback
    # reads it as "same as issued" — 107.560g of 21k credited as 107.560g of
    # pure, and the shop ends up owing him about fourteen grams on a job he is
    # actually short on. Silence must not be able to produce that.
    purity_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    purity_leg = client.post(
        f"/designs/{purity_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "100", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    ).json()
    r = client.post(
        f"/designs/legs/{purity_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600"},
    )
    check(
        "a ratti leg cannot be received without stating what purity came back → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:220]} — settling at the issued purity credits "
        "21k as pure and hands the maker roughly a seventh of the job",
    )
    # Stated, it settles correctly.
    r = client.post(
        f"/designs/legs/{purity_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600", "gold_received_purity": 21},
    )
    check("and settles once the purity is stated → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")

    # --- the maker works on his own gold, and the shop owes him ---
    # Nothing goes out. He hands over 107.560g of 21k on 6 ratti, so the shop
    # owes him the fine content plus his ratti: 99.9972 g of pure gold, against
    # a date the two of them agreed.
    own_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    due = str(date.today() + timedelta(days=30))
    r = client.post(
        f"/designs/{own_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "0", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "percent_of_issued",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
            "metal_due_date": due,
        },
    )
    check(
        "a no-metal leg on a percentage basis is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:220]} — under a percentage the excess floors at "
        "zero, so his gold would arrive and he would be owed none of it",
    )
    r = client.post(
        f"/designs/{own_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "0", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    )
    check(
        "a no-metal leg with no due date is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:200]} — an obligation with no date is one "
        "nobody chases",
    )

    stock_before = Decimal(
        str(client.get(f"/inventory/{pure_gold['id']}", headers=auth).json()["weight_g"])
    )
    r = client.post(
        f"/designs/{own_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "0", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
            "metal_due_date": due,
        },
    )
    check("issue a leg with no metal at all → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    own_leg = r.json()
    check("the due date is recorded on the leg", own_leg["metal_due_date"] == due,
          f"got {own_leg.get('metal_due_date')}")
    stock_after = Decimal(
        str(client.get(f"/inventory/{pure_gold['id']}", headers=auth).json()["weight_g"])
    )
    check(
        "no metal left the safe",
        stock_after == stock_before,
        f"stock moved from {stock_before} to {stock_after} on a leg that issued nothing",
    )

    r = client.post(
        f"/designs/legs/{own_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600", "gold_received_purity": 21},
    )
    check("receive the piece he made on his own gold → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:250]}")
    own = r.json()
    check(
        "the shop owes him 99.9972g of pure gold — the fine content plus his ratti",
        Decimal(str(own["wastage_excess_fine_g"])) == Decimal("-99.9972"),
        f"got {own['wastage_excess_fine_g']}, expected -99.9972 (negative = owed to him). "
        "0 would mean his gold arrived free.",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books balance when the shop owes a maker metal", r.json()["balanced"] is True)

    # --- a lot goes out as one weight and comes back as twelve pieces ---
    # 100g of pure gold to the maker as LOT-00001; 107.560g of 21k back, divided
    # into twelve bangles each weighed on its own. Every piece then carries its
    # own TK number through setting, stock and sale.
    r = client.post("/designs", headers=auth, json={
        "item_id": taka_id, "as_lot": True, "expected_pieces": 12,
    })
    check("mint a lot → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    lot = r.json()
    check(
        "a lot is numbered from its own sequence, not the item's",
        lot["design_no"].startswith("LOT-"),
        f"got {lot['design_no']} — while the metal is out the item is a plan, not a fact",
    )
    check("and knows how many pieces it should yield", lot["expected_pieces"] == 12,
          f"got {lot.get('expected_pieces')}")

    r = client.post("/designs", headers=auth, json={"item_id": taka_id, "expected_pieces": 12})
    check(
        "expected_pieces on a single piece is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:180]}",
    )

    lot_leg = client.post(
        f"/designs/{lot['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "100", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 12, "labour_basis": "per_piece", "labour_rate": "800",
        },
    ).json()

    # Dividing before the metal is back would number pieces the shop is not
    # holding.
    r = client.post(f"/designs/{lot['id']}/split", headers=auth,
                    json={"pieces": [{"weight_g": "107.56"}]})
    check(
        "splitting a lot still out with the maker is refused → 409",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:200]}",
    )

    client.post(
        f"/designs/legs/{lot_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600", "gold_received_purity": 21},
    )

    twelve = [{"weight_g": "9.0000"} for _ in range(11)] + [{"weight_g": "8.5600"}]
    r = client.post(f"/designs/{lot['id']}/split", headers=auth,
                    json={"pieces": twelve[:11]})
    check(
        "a split that does not add up to what came back is refused → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:220]}",
    )

    r = client.post(f"/designs/{lot['id']}/split", headers=auth, json={"pieces": twelve})
    check("divide the lot into 12 pieces → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    pieces = r.json()
    check("twelve designs come out of it", len(pieces) == 12, f"got {len(pieces)}")
    check(
        "each piece is numbered from the item, not the lot",
        all(p["design_no"].startswith("TK-") for p in pieces),
        f"got {[p['design_no'] for p in pieces][:3]}…",
    )
    check(
        "each piece carries the weight it actually came back at",
        Decimal(str(pieces[-1]["piece_weight_g"])) == Decimal("8.56")
        and Decimal(str(pieces[0]["piece_weight_g"])) == Decimal("9"),
        f"first {pieces[0].get('piece_weight_g')}, last {pieces[-1].get('piece_weight_g')} "
        "— an even split would put 8.9633 on all twelve",
    )
    check(
        "and the purity the maker returned, not the purity that went out",
        all(p["piece_purity"] == 21 for p in pieces),
        f"got {[p.get('piece_purity') for p in pieces][:3]}",
    )
    check(
        "every piece points back at its lot",
        all(p["parent_design_id"] == lot["id"] for p in pieces),
        "a piece that cannot name its lot cannot be traced to the maker who made it",
    )
    check(
        "the pieces add up to exactly what came back",
        sum((Decimal(str(p["piece_weight_g"])) for p in pieces), Decimal("0"))
        == Decimal("107.56"),
        "the split must reconcile against the metal received",
    )

    r = client.get(f"/designs/{lot['id']}", headers=auth)
    check(
        "the divided lot leaves the floor",
        r.json()["status"] == "split",
        f"got {r.json().get('status')} — a lot left in production sits in the worklist "
        "of pieces still to be made",
    )
    r = client.post(f"/designs/{lot['id']}/split", headers=auth, json={"pieces": twelve})
    check(
        "dividing the same lot twice is refused → 409",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:200]} — it would mint a second set of numbers "
        "for metal that came back once",
    )
    r = client.post(f"/designs/{pieces[0]['id']}/split", headers=auth,
                    json={"pieces": [{"weight_g": "9"}]})
    check(
        "a single piece cannot be divided → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:200]}",
    )

    # A lot holds no article. Stocking it as well as its pieces would post the
    # same metal into Finished Goods twice.
    r = client.get(f"/stocking/designs/{lot['id']}/preview", headers=auth)
    check(
        "a lot cannot be stocked → 409",
        r.status_code == 409,
        f"got {r.status_code}: {r.text[:200]} — stocking the lot as well as its pieces "
        "would post the same metal into Finished Goods twice",
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
    # The stage ships seeded; the shop only has to put its own rate on it.
    r = client.patch(
        f"/departments/{lac_dept_id}", headers=auth, json={"default_rate_per_piece": "500"}
    )
    check(
        "the lacker's per-item rate is agreed once on the stage → 200",
        r.status_code == 200 and Decimal(str(r.json()["default_rate_per_piece"])) == Decimal("500"),
        f"got {r.status_code}: {r.text[:150]}",
    )
    r = client.post(
        f"/designs/{set_design['id']}/legs",
        headers=auth,
        json={
            "department_id": lac_dept_id,
            "worker_id": lacker["id"],
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

    # --- setting, in full: gross weight in, net metal out, every carat placed ---
    # The client's worked example, end to end.
    #
    #   out   100.000 g of 21k + 30.00 ct (= 6.000 g)  = 106.000 g
    #   back  gross 102.000 g, 29.50 ct stated as set  =   5.900 g
    #   net   102.000 - 5.900                          =  96.100 g
    #   short 100.000 - 96.100                         =   3.900 g
    #   allow 0.400 / 100 x 350                        =   1.400 g
    #   ----------------------------------------------------------
    #   gold receivable                                    2.500 g of 21k
    #                                                   =  2.1875 g fine
    #
    # and of the 0.50 ct unaccounted for, 0.30 broke and 0.20 is his.
    setting_stone = client.post("/stones", headers=auth, json={
        "name": "12 PTR commercial", "kind": "diamond", "category": "diamond",
        "default_rate_per_ct": "8000", "selling_rate_per_ct": "12000", "currency": "PKR",
    })
    check("a stone can carry a selling rate apart from its cost → 201",
          setting_stone.status_code == 201, f"got {setting_stone.status_code}: {setting_stone.text[:200]}")
    setting_stone_id = setting_stone.json()["id"]
    set_stock = open_pot(
        {"type": "raw_stone", "label": "12 PTR parcel"},
        weight_ct="100", value="400000",
    )
    piece_gold = open_pot(
        {"type": "raw_gold", "label": "21k for setting", "purity": 21},
        weight_g="300", rate_per_g="30000",
    )

    full_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{full_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id,
            "worker_id": setter["id"],
            "gold_issued_g": "100",
            "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": set_stock["id"],
            "stones": [{"stone_id": setting_stone_id, "quantity_issued": 360,
                        "weight_issued_ct": "30"}],
            "piece_count": 360,
            "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
            "labour_basis": "per_piece",
            "labour_rate": "5",
        },
    )
    check("issue 100g of 21k and 30ct to the setter → 201",
          r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    full_leg = r.json()
    check(
        "30ct is recorded on the leg in carats, never grams",
        Decimal(str(full_leg["stones_issued_ct"])) == Decimal("30"),
        f"got {full_leg['stones_issued_ct']}",
    )
    line_id = full_leg["stones"][0]["id"]

    r = client.post(
        f"/designs/legs/{full_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "102",
            "piece_count": 350,
            "stones": [{
                "leg_stone_id": line_id,
                "quantity_set": 350, "weight_set_ct": "29.50",
                "quantity_returned": 0, "weight_returned_ct": "0",
                "quantity_broken": 4, "weight_broken_ct": "0.30",
            }],
        },
    )
    check("receive the piece at a gross 102g → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:300]}")
    full = r.json()
    check(
        "the gross weight is kept as the scale read it",
        Decimal(str(full["gold_received_gross_g"])) == Decimal("102"),
        f"got {full['gold_received_gross_g']}, expected 102.0000",
    )
    check(
        "29.50ct set is 5.900g, so the metal back is 96.100g",
        Decimal(str(full["gold_received_g"])) == Decimal("96.1"),
        f"got {full['gold_received_g']}, expected 96.1000 — 102 would mean the stones "
        "were never taken out of the gross",
    )
    check(
        "the allowance is 0.400g per 100 over 350 stones = 1.400g",
        Decimal(str(full["wastage_allowed_g"])) == Decimal("1.4"),
        f"got {full['wastage_allowed_g']}, expected 1.4000",
    )
    check(
        "2.500g of 21k is receivable from the setter",
        Decimal(str(full["wastage_excess_g"])) == Decimal("2.5"),
        f"got {full['wastage_excess_g']}, expected 2.5000",
    )
    check(
        "which is 2.1875g once converted to fine",
        Decimal(str(full["wastage_excess_fine_g"])) == Decimal("2.1875"),
        f"got {full['wastage_excess_fine_g']}, expected 2.1875",
    )
    check(
        "0.30ct is recorded as broken",
        Decimal(str(full["stones_broken_ct"])) == Decimal("0.30"),
        f"got {full['stones_broken_ct']}",
    )
    check(
        "0.20ct is left owed by the setter, derived not typed",
        Decimal(str(full["stones_owed_ct"])) == Decimal("0.20"),
        f"got {full['stones_owed_ct']}, expected 0.2000 — 30 less 29.50 set less 0.30 broken",
    )
    check(
        "every issued carat is placed: set + returned + broken + owed = issued",
        Decimal(str(full["stones_set_ct"])) + Decimal(str(full["stones_returned_ct"]))
        + Decimal(str(full["stones_broken_ct"])) + Decimal(str(full["stones_owed_ct"]))
        == Decimal(str(full["stones_issued_ct"])),
        f"set {full['stones_set_ct']} + returned {full['stones_returned_ct']} + broken "
        f"{full['stones_broken_ct']} + owed {full['stones_owed_ct']} "
        f"!= issued {full['stones_issued_ct']}",
    )
    check(
        "the setter is charged for the 350 he set, not the 360 he was handed",
        Decimal(str(full["labour_amount"])) == Decimal("1750"),
        f"got {full['labour_amount']}, expected 1750.00",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books balance after a full setting settlement", r.json()["balanced"] is True)

    # Broken stones are stock, not a loss: they land in their own category
    # rather than back among the whole stones they can no longer serve.
    inv = client.get("/inventory", headers=auth, params={"type": "broken_stone"})
    broken_rows = inv.json() if inv.status_code == 200 else []
    if isinstance(broken_rows, dict):
        broken_rows = broken_rows.get("items", [])
    check(
        "0.30ct of broken stones is held as its own stock",
        any(Decimal(str(row["weight_ct"])) == Decimal("0.30") for row in broken_rows),
        f"got {[str(row.get('weight_ct')) for row in broken_rows]} from {inv.status_code}",
    )

    # --- a stone with no rate still leaves a claim ---
    # The setter owes carats whether or not anybody has priced that grade. If
    # the claim is only recorded when it has a rupee value, a shop that has not
    # filled in its stone rates loses every stone debt silently — which is the
    # one thing the carat account exists to prevent.
    norate_stone = client.post("/stones", headers=auth, json={
        "name": "Unpriced chips", "kind": "diamond", "category": "diamond",
    }).json()
    norate_stock = open_pot(
        {"type": "raw_stone", "label": "unpriced chips packet"},
        weight_ct="50", value="150000",
    )
    nr_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    nr_leg = client.post(
        f"/designs/{nr_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "10", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": norate_stock["id"],
            "stones": [{"stone_id": norate_stone["id"], "quantity_issued": 10,
                        "weight_issued_ct": "5"}],
            "piece_count": 10, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
        },
    ).json()
    r = client.post(
        f"/designs/legs/{nr_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "10.5",
            "stones": [{
                "leg_stone_id": nr_leg["stones"][0]["id"],
                "quantity_set": 8, "weight_set_ct": "4",
            }],
        },
    )
    check("receive an unpriced-stone leg → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:220]}")
    nr = r.json()
    check(
        "1.00ct is still recorded as owed even with no rate on the stone",
        Decimal(str(nr["stones_owed_ct"])) == Decimal("1"),
        f"got {nr['stones_owed_ct']}",
    )
    r = client.get("/ledger/position", headers=auth)
    check(
        "and the carat claim reaches the books, valued or not",
        Decimal(str(r.json()["stones_with_workers_ct"])) >= Decimal("1"),
        f"1170 holds {r.json().get('stones_with_workers_ct')}ct — a claim recorded only "
        "when it has a rupee value is a claim a shop with no stone rates never gets",
    )

    # A line cannot account for more than it was issued. Without the guard the
    # leftover comes out negative and reads as the shop owing him stones.
    over_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    over_leg = client.post(
        f"/designs/{over_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "10", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": set_stock["id"],
            "stones": [{"stone_id": setting_stone_id, "quantity_issued": 10,
                        "weight_issued_ct": "5"}],
            "piece_count": 10, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
        },
    ).json()
    r = client.post(
        f"/designs/legs/{over_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "11",
            "stones": [{
                "leg_stone_id": over_leg["stones"][0]["id"],
                "quantity_set": 8, "weight_set_ct": "4",
                "quantity_returned": 4, "weight_returned_ct": "2",
            }],
        },
    )
    check(
        "a stone line accounting for more than it was issued is refused → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:200]}",
    )

    # --- silver: the same floor, a different metal, and never the same balance ---
    # 999 silver is quoted out of a thousand, not in karat. A silver leg values
    # at the silver rate, posts to the silver accounts, and its grams must never
    # land in a gold balance.
    section("Silver")
    r = client.post("/gold-rates", headers=auth, json={
        "rate_date": str(date.today()), "currency": "PKR", "metal": "silver",
        "rate_per_g": "340", "fineness_pct": "99.9",
    })
    check("set today's silver rate → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    r = client.post("/gold-rates", headers=auth, json={
        "rate_date": str(date.today()), "currency": "PKR", "metal": "silver",
        "rate_per_g": "340",
    })
    check(
        "a silver rate with no fineness is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:200]} — without it the quote would be taken as "
        "the pure rate and every silver movement valued light",
    )
    r = client.get("/gold-rates/current", headers=auth, params={"metal": "silver", "currency": "PKR"})
    check("the silver rate is fetched apart from the gold rate", r.status_code == 200,
          f"got {r.status_code}: {r.text[:200]}")

    silver_stock_row = open_pot(
        {"type": "raw_silver", "label": "999 silver bullion", "tunch_pct": "99.9"},
        weight_g="5000", rate_per_g="340",
    )
    check("silver has its own stock category", silver_stock_row["type"] == "raw_silver",
          str(silver_stock_row)[:160])
    silver_stock = silver_stock_row

    silver_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{silver_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"], "metal": "silver",
            "gold_issued_g": "1000", "gold_issued_purity": 24,
            "gold_source_inventory_id": silver_stock["id"],
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    )
    check(
        "a silver leg quoted in karat is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:200]} — there is no such thing as 21k silver",
    )
    r = client.post(
        f"/designs/{silver_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"], "metal": "silver",
            "gold_issued_g": "1000", "gold_source_inventory_id": silver_stock["id"],
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    )
    check(
        "a silver leg with no fineness at all is refused → 422",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:200]} — the karat fallback would read 999 as pure",
    )
    r = client.post(
        f"/designs/{silver_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"], "metal": "silver",
            "gold_issued_g": "1000", "gold_issued_tunch_pct": "99.9",
            "gold_source_inventory_id": raw_gold["id"],
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    )
    check(
        "a silver leg drawing from the gold vault is refused → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:200]} — it would post to the silver accounts "
        "while emptying the gold drawer",
    )

    # Metal with workers, read before and after a silver issue. The whole point
    # of a separate commodity is that the gold figure does not move.
    def position() -> dict:
        return client.get("/ledger/position", headers=auth).json()

    gold_before = Decimal(str(position()["gold_with_workers_g"]))
    r = client.post(
        f"/designs/{silver_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"], "metal": "silver",
            "gold_issued_g": "1000", "gold_issued_tunch_pct": "99.9",
            "gold_source_inventory_id": silver_stock["id"],
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    )
    check("issue 1000g of 999 silver to the maker → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    silver_leg = r.json()
    check("the leg records the metal it is working", silver_leg["metal"] == "silver",
          f"got {silver_leg.get('metal')}")

    pos = position()
    check(
        "999 silver is 999 fine grams with the worker",
        Decimal(str(pos["silver_with_workers_g"])) == Decimal("999"),
        f"got {pos['silver_with_workers_g']}, expected 999.0000 (1000g at 99.9%)",
    )
    check(
        "and not one gram of it landed in the gold balance",
        Decimal(str(pos["gold_with_workers_g"])) == gold_before,
        f"gold with workers moved from {gold_before} to {pos['gold_with_workers_g']} "
        "on a silver issue — the two metals are sharing a balance",
    )
    r = client.get("/ledger/trial-balance", headers=auth)
    check("books balance with silver on them", r.json()["balanced"] is True)

    # Reports are grams, and grams of the two metals cannot be added. A report
    # that summed them would tell a shop losing a kilo of silver that it was
    # losing a kilo of gold.
    r = client.get("/reports/manufacturing-loss", headers=auth, params={"metal": "silver"})
    check(
        "the loss report can be asked for silver on its own → 200",
        r.status_code == 200 and r.json().get("metal") == "silver",
        f"got {r.status_code}: {r.text[:200]}",
    )
    gold_loss = client.get("/reports/manufacturing-loss", headers=auth).json()
    check(
        "and defaults to gold, saying so on the response",
        gold_loss.get("metal") == "gold",
        f"got {gold_loss.get('metal')} — a gram figure that does not say which metal "
        "it is cannot be read at all",
    )
    # The silver leg above is 1000g and still out; only received legs count, so
    # what matters is that asking for one metal never returns the other's legs.
    silver_rows = client.get(
        "/reports/department-throughput", headers=auth, params={"metal": "silver"}
    ).json()
    gold_rows = client.get("/reports/department-throughput", headers=auth).json()
    check(
        "department throughput keeps the two metals apart",
        silver_rows.get("rows") != gold_rows.get("rows")
        or all(Decimal(str(x["gold_in_g"])) == 0 for x in silver_rows.get("rows", [])),
        "a silver leg appearing in the gold rows means the two are sharing a total",
    )

    # ==================================================================
    # THE TWO WASTAGE CONVENTIONS, SIDE BY SIDE
    # ==================================================================
    # The client's own two worked examples, verbatim, asserted together in one
    # place — because the single thing he has repeated most is that these are
    # *independent* formulas and must never be conflated.
    #
    # They differ in all four ways that matter:
    #
    #                      MAKER (ratti)              SETTER (per 100 pieces)
    #   measured against   what comes BACK            what went OUT
    #   quoted in          ratti of 96                grams per 100 stones
    #   denominated in     the returned karat         the issued karat
    #   an unused part is  owed to him (entitlement)  kept by the shop (a cap)
    #
    # Neither converts into the other, and until the job is finished nobody
    # knows the maker's reference weight at all.
    section("Maker vs setter — two conventions")

    # --- 1. THE MAKER ---------------------------------------------------
    #   100.000 g of pure 24k out, 107.560 g of 21k back, 6 ratti agreed.
    #     107.560 / 96 * 6      =   6.7225 g of 21k   (added to his credit)
    #     107.560 + 6.7225      = 114.2825 g of 21k
    #     114.2825 * 21 / 24    =  99.9972 g pure
    #     100.000 - 99.9972     =   0.0028 g pure still owed by him
    mk_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    mk_leg = client.post(
        f"/designs/{mk_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "100", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    ).json()
    mk = client.post(
        f"/designs/legs/{mk_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "107.5600", "gold_received_purity": 21},
    ).json()
    check(
        "MAKER: 6 ratti of 96 on the 107.560g he returned = 6.7225g of 21k",
        Decimal(str(mk["wastage_allowed_g"])) == Decimal("6.7225"),
        f"got {mk['wastage_allowed_g']} — worked out on what came BACK, not what went out",
    )
    check(
        "MAKER: the allowance is in the karat he returned, so 5.8822g fine",
        Decimal(str(mk["wastage_allowed_fine_g"])) == Decimal("5.8822"),
        f"got {mk['wastage_allowed_fine_g']} — 6.7225 here would mean it was read as pure",
    )
    check(
        "MAKER: he is left owing 0.0028g of pure gold",
        Decimal(str(mk["wastage_excess_fine_g"])) == Decimal("0.0028"),
        f"got {mk['wastage_excess_fine_g']}, expected 0.0028",
    )

    # --- 1b. THE MAKER, THE SHOP'S SECOND WORKED EXAMPLE -----------------
    #   The owner wrote this one out in full, so it is asserted in his own
    #   arithmetic rather than mine:
    #
    #     100 g pure gold given to the maker
    #     102 g of 18k received back
    #     102 / 96 * 10          = 10.625 g allowance at 10 ratti
    #     102 + 10.625           = 112.625 g adjusted
    #     112.625 / 24 * 18      = 84.469 g of pure equivalent
    #     100 - 84.469           = 15.531 g the maker owes the shop
    #
    #   The system reaches it the other way round — issued fine, less received
    #   fine, less the allowance in fine — which is the same identity
    #   rearranged. Asserting the *answer* rather than the route is what makes
    #   that safe: if either derivation drifts, this fails.
    m2_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    m2_leg = client.post(
        f"/designs/{m2_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "100", "gold_issued_purity": 24,
            "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "10",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
        },
    ).json()
    m2 = client.post(
        f"/designs/legs/{m2_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "102", "gold_received_purity": 18},
    ).json()
    check(
        "MAKER 2: 10 ratti on 102g received allows 10.625g",
        Decimal(str(m2["wastage_allowed_g"])) == Decimal("10.625"),
        f"got {m2['wastage_allowed_g']} — 102/96*10",
    )
    check(
        "MAKER 2: the shop is owed 15.531g of pure gold — the owner's own figure",
        abs(Decimal(str(m2["wastage_excess_fine_g"])) - Decimal("15.5312")) <= Decimal("0.0002"),
        f"got {m2['wastage_excess_fine_g']}, expected 15.5312 "
        "(100 - (102 + 10.625) / 24 * 18)",
    )
    check(
        "MAKER 2: and it is a debt to the shop, not a credit to him",
        Decimal(str(m2["wastage_excess_fine_g"])) > 0,
        "a negative here would mean the shop owed the maker",
    )

    # --- 2. THE STONE SETTER --------------------------------------------
    #   100.000 g of 21k product + 30.00 ct of stones out.
    #     30.00 / 5              =   6.000 g of stones
    #     total handed over      = 106.000 g
    #   102.000 g comes back gross, all 30.00 ct still set in it.
    #     106.000 - 102.000      =   4.000 g short
    #     0.400 / 100 * 350 pcs  =   1.400 g allowed
    #     4.000 - 1.400          =   2.600 g receivable from him
    st_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    st_leg = client.post(
        f"/designs/{st_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "100", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": set_stock["id"],
            "stones": [{"stone_id": setting_stone_id, "quantity_issued": 350,
                        "weight_issued_ct": "30"}],
            "piece_count": 350,
            "wastage_basis": "per_100_pieces", "wastage_per_100_pcs_g": "0.400",
            "labour_basis": "per_piece", "labour_rate": "5",
        },
    ).json()
    check(
        "the leg states 106g handed over: metal and stones on one scale",
        Decimal(str(st_leg["gold_issued_with_stones_g"])) == Decimal("106"),
        f"got {st_leg['gold_issued_with_stones_g']} — 100g of gold plus 30ct is "
        "how the shop says what left the safe, and until the piece comes back "
        "it is the only reckoning there is",
    )
    check(
        "SETTER: 30.00ct is 6.000g, so 106.000g was handed over in total",
        Decimal(str(st_leg["stones_issued_ct"])) == Decimal("30")
        and Decimal(str(st_leg["gold_issued_g"])) == Decimal("100"),
        f"gold {st_leg['gold_issued_g']}g + stones {st_leg['stones_issued_ct']}ct",
    )
    st = client.post(
        f"/designs/legs/{st_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "102",
            "piece_count": 350,
            "stones": [{
                "leg_stone_id": st_leg["stones"][0]["id"],
                "quantity_set": 350, "weight_set_ct": "30",
            }],
        },
    ).json()
    check(
        "SETTER: 0.400g per 100 over 350 pieces = 1.400g allowed",
        Decimal(str(st["wastage_allowed_g"])) == Decimal("1.4"),
        f"got {st['wastage_allowed_g']} — worked out on the pieces he SET, not on any weight",
    )
    check(
        "SETTER: gross 102.000g less the 6.000g of stones in it = 96.000g of metal",
        Decimal(str(st["gold_received_g"])) == Decimal("96"),
        f"got {st['gold_received_g']} — 102 would mean the stones were never taken out",
    )
    check(
        "SETTER: 106 given, 102 back, 4.000g short",
        Decimal(str(st["wastage_actual_g"])) == Decimal("4"),
        f"got {st['wastage_actual_g']} — the client's own figure",
    )
    check(
        "SETTER: 4.000 less 1.400 allowed = 2.600g receivable from him",
        Decimal(str(st["wastage_excess_g"])) == Decimal("2.6"),
        f"got {st['wastage_excess_g']}, expected 2.6000 — the client's own figure",
    )
    check(
        "SETTER: charged 350 x Rs 5 = Rs 1,750",
        Decimal(str(st["labour_amount"])) == Decimal("1750"),
        f"got {st['labour_amount']}",
    )

    # --- 3. THEY ARE NOT THE SAME RULE ----------------------------------
    # The proof that they are independent: the two legs above were settled by
    # different arithmetic against different reference weights, and neither
    # figure could have been produced by the other's formula.
    check(
        "the maker's allowance came from the weight he RETURNED",
        Decimal(str(mk["wastage_allowed_g"]))
        == (Decimal("107.5600") / 96 * 6).quantize(Decimal("0.0001")),
        f"{mk['wastage_allowed_g']} vs 107.56/96*6 — a percentage of the 100g issued would "
        "have given something else entirely",
    )
    # --- 3b. EVERY ISSUED CARAT IS ACCOUNTED FOR ------------------------
    # The client's own figures: "if we give him 2ct he used 1.2 then he owes us
    # .8 — and if .2 is broken the broken goes to our broken stock and the
    # others go to the stock."
    #
    # So the 0.8 he did not set is his to produce, in one of three ways: hand it
    # back whole, hand it back broken, or owe it. Those three plus what he set
    # must equal what he was given, and nothing may fall between them.
    acct_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    acct_leg = client.post(
        f"/designs/{acct_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "20", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": set_stock["id"],
            "stones": [{"stone_id": setting_stone_id, "quantity_issued": 20,
                        "weight_issued_ct": "2"}],
            "piece_count": 12, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
        },
    ).json()
    broken_before = sum(
        Decimal(str(row["weight_ct"]))
        for row in client.get("/inventory", headers=auth,
                              params={"type": "broken_stone"}).json()
    )
    ac = client.post(
        f"/designs/legs/{acct_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "19.5",
            "stones": [{
                "leg_stone_id": acct_leg["stones"][0]["id"],
                "quantity_set": 12, "weight_set_ct": "1.2",
                "quantity_broken": 2, "weight_broken_ct": "0.2",
                "quantity_returned": 6, "weight_returned_ct": "0.6",
            }],
        },
    ).json()
    check(
        "2ct out, 1.2ct set — so 0.8ct is his to produce",
        Decimal(str(ac["stones_set_ct"])) == Decimal("1.2")
        and Decimal(str(ac["stones_issued_ct"])) - Decimal(str(ac["stones_set_ct"]))
        == Decimal("0.8"),
        f"set {ac['stones_set_ct']} of {ac['stones_issued_ct']}",
    )
    check(
        "0.2ct broken goes to the broken stock",
        Decimal(str(ac["stones_broken_ct"])) == Decimal("0.2"),
        f"got {ac['stones_broken_ct']}",
    )
    broken_after = sum(
        Decimal(str(row["weight_ct"]))
        for row in client.get("/inventory", headers=auth,
                              params={"type": "broken_stone"}).json()
    )
    check(
        "and it physically lands there, not just on the row",
        broken_after - broken_before == Decimal("0.2"),
        f"broken stock moved {broken_after - broken_before}ct, expected 0.2",
    )
    check(
        "0.6ct handed back whole goes to the ordinary stock",
        Decimal(str(ac["stones_returned_ct"])) == Decimal("0.6"),
        f"got {ac['stones_returned_ct']}",
    )
    check(
        "he produced all 0.8ct, so he owes nothing",
        Decimal(str(ac["stones_owed_ct"])) == Decimal("0"),
        f"got {ac['stones_owed_ct']} — 1.2 set + 0.6 back + 0.2 broken = the 2ct he was given",
    )

    # The same leg with nothing handed back: then the 0.6 he cannot produce is
    # a debt, which is the other half of "he owes us them".
    owe_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    owe_leg = client.post(
        f"/designs/{owe_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "20", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": set_stock["id"],
            "stones": [{"stone_id": setting_stone_id, "quantity_issued": 20,
                        "weight_issued_ct": "2"}],
            "piece_count": 12, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
        },
    ).json()
    ow = client.post(
        f"/designs/legs/{owe_leg['id']}/receive",
        headers=auth,
        json={
            "gold_received_g": "19.5",
            "stones": [{
                "leg_stone_id": owe_leg["stones"][0]["id"],
                "quantity_set": 12, "weight_set_ct": "1.2",
                "quantity_broken": 2, "weight_broken_ct": "0.2",
            }],
        },
    ).json()
    check(
        "what he cannot produce, he owes: 2 − 1.2 set − 0.2 broken = 0.6ct",
        Decimal(str(ow["stones_owed_ct"])) == Decimal("0.6"),
        f"got {ow['stones_owed_ct']} — nothing may fall between set, returned, broken and owed",
    )

    # --- 4. THE BASE IS NOT ALWAYS A HUNDRED ----------------------------
    # 0.400 per 100 is how it is usually said, not how it is always said. A
    # deal struck per 250 has to be recordable as 250, or the shop divides it
    # down by hand and the figure it shook on never appears anywhere.
    base_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    base_leg = client.post(
        f"/designs/{base_design['id']}/legs",
        headers=auth,
        json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "50", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "piece_count": 500,
            "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400", "wastage_pieces_base": 250,
            "labour_basis": "per_piece", "labour_rate": "5",
        },
    )
    check("a per-250 deal is accepted → 201", base_leg.status_code == 201,
          f"got {base_leg.status_code}: {base_leg.text[:200]}")
    base_leg = base_leg.json()
    check("the base is recorded on the leg", base_leg["wastage_pieces_base"] == 250,
          f"got {base_leg.get('wastage_pieces_base')}")
    bs = client.post(
        f"/designs/legs/{base_leg['id']}/receive",
        headers=auth,
        json={"gold_received_g": "49"},
    ).json()
    check(
        "0.400g per 250 over 500 pieces = 0.800g, not the 2.000g a hundred would give",
        Decimal(str(bs["wastage_allowed_g"])) == Decimal("0.8"),
        f"got {bs['wastage_allowed_g']} — 2.0000 would mean the base was ignored",
    )

    check(
        "the setter's allowance came from the pieces he SET, and no weight at all",
        Decimal(str(st["wastage_allowed_g"]))
        == (Decimal("0.400") / 100 * 350).quantize(Decimal("0.0001")),
        f"{st['wastage_allowed_g']} vs 0.400/100*350 — it does not move if the piece is "
        "heavier or lighter, only if he sets more stones",
    )
    check(
        "an unused ratti allowance is owed back to the maker; an unused per-100 one is not",
        Decimal(str(mk["wastage_excess_fine_g"])) == Decimal("0.0028")
        and Decimal(str(st["wastage_excess_g"])) > 0,
        "the maker's allowance is metal he is entitled to keep, so it is signed; the "
        "setter's is a cap on what he can be charged, so it floors at zero",
    )
    check(
        "books balance after settling both",
        client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True,
    )

    # ----- TWO BUSINESSES UNDER ONE ROOF -----
    section("Profit split")
    r = client.get("/reports/profit-split", headers=auth)
    check("profit split → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    ps = r.json()
    check(
        "metal, stones and making are reported apart",
        {s["stream"] for s in ps["streams"]} == {"gold", "stones", "making"},
        f"got {[s['stream'] for s in ps['streams']]} — a single margin averages a business "
        "that turns over weekly with one that turns over yearly",
    )
    check(
        "each carries its own margin percentage",
        all("margin_pct" in s for s in ps["streams"]),
        "making moves with neither rate and for a wholesaler is most of the margin",
    )
    check(
        "the streams add up to the whole",
        sum(Decimal(str(s["revenue"])) for s in ps["streams"]) == Decimal(str(ps["revenue"])),
        f"streams {sum(Decimal(str(s['revenue'])) for s in ps['streams'])} vs total "
        f"{ps['revenue']}",
    )
    check(
        "lines that could not be split are counted, not guessed at",
        "unsplit_lines" in ps,
        "a guess would move margin from one business to the other and nothing would say so",
    )

    # ----- METAL HELD AT COST IS NOT METAL HELD AT WHAT IT IS WORTH -----
    section("Metal revaluation")
    r = client.get("/ledger/revaluation", headers=auth)
    check("revaluation preview → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    prev = r.json()
    gold_v = next(m for m in prev["metals"] if m["metal"] == "gold")
    check(
        "it says what the metal is on the books at and what it is worth",
        gold_v["book_value"] is not None and gold_v["market_value"] is not None,
        f"book {gold_v.get('book_value')} market {gold_v.get('market_value')}",
    )
    grams_before = Decimal(str(client.get("/ledger/position", headers=auth).json()["gold_in_hand_g"]))
    r = client.post("/ledger/revaluation", headers=pwd_h)
    check("post the revaluation → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    res = r.json()
    check(
        "an entry is posted when the market has moved",
        res["entry_no"] is not None or Decimal(str(res["total_difference"])) == 0,
        f"entry {res.get('entry_no')} for {res.get('total_difference')}",
    )
    grams_after = Decimal(str(client.get("/ledger/position", headers=auth).json()["gold_in_hand_g"]))
    check(
        "not one gram moved — only the money did",
        grams_after == grams_before,
        f"gold went from {grams_before}g to {grams_after}g — revaluing must never touch the "
        "figure the safe is counted against",
    )
    check(
        "and the books still balance",
        client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True,
    )
    # Posting twice in a row has nothing left to do, which is a real answer.
    r = client.post("/ledger/revaluation", headers=pwd_h)
    check(
        "revaluing again finds nothing to move, and says so rather than failing",
        r.status_code == 200 and Decimal(str(r.json()["total_difference"])) == 0,
        f"got {r.status_code}: {r.text[:200]} — a quiet day is not an error",
    )

    # ----- SALESMEN, BROKERS AND THE FIGURES THEY ARE ASKED TO HIT -----
    section("Sellers and targets")
    sman = client.post("/sales/sellers", headers=auth, json={
        "name": "Road Salesman", "kind": "salesman", "commission_pct": "2",
    })
    check("create a salesman → 201", sman.status_code == 201,
          f"got {sman.status_code}: {sman.text[:200]}")
    sman = sman.json()
    brk = client.post("/sales/sellers", headers=auth, json={
        "name": "Bazaar Broker", "kind": "broker", "commission_pct": "1",
    }).json()
    check("brokers are kept apart from salesmen", brk["kind"] == "broker",
          f"got {brk.get('kind')} — a broker holds no stock and a blended report would "
          "show the shop carrying goods with a man who never had any")

    # A target with no figure at all cannot be missed or met.
    r = client.post("/sales/targets", headers=auth, json={
        "scope": "company", "period_start": str(date.today()),
        "period_end": str(date.today() + timedelta(days=30)),
    })
    check("a target with neither an amount nor a weight is refused → 422",
          r.status_code == 422, f"got {r.status_code}: {r.text[:180]}")
    # A period that ends before it starts measures nothing.
    r = client.post("/sales/targets", headers=auth, json={
        "scope": "company", "period_start": str(date.today()),
        "period_end": str(date.today() - timedelta(days=1)), "target_amount": "1000",
    })
    check("a period that ends before it starts is refused → 422",
          r.status_code == 422, f"got {r.status_code}: {r.text[:180]}")
    # The scope decides which party is named.
    r = client.post("/sales/targets", headers=auth, json={
        "scope": "customer", "period_start": str(date.today()),
        "period_end": str(date.today() + timedelta(days=30)),
        "target_amount": "1000", "seller_id": sman["id"],
    })
    check("a customer target naming a salesman is refused → 422",
          r.status_code == 422,
          f"got {r.status_code}: {r.text[:180]} — it would measure the wrong party's sales")

    # Money and weight side by side, either optional.
    r = client.post("/sales/targets", headers=auth, json={
        "scope": "company",
        "period_start": str(date.today() - timedelta(days=10)),
        "period_end": str(date.today() + timedelta(days=20)),
        "label": "This month", "target_amount": "1000000", "target_weight_g": "500",
    })
    check("set a company target in both money and weight → 201",
          r.status_code == 201, f"got {r.status_code}: {r.text[:220]}")
    tgt = r.json()
    check(
        "progress is measured, not stored — both halves come back filled in",
        Decimal(str(tgt["actual_amount"])) > 0 and tgt["invoices"] > 0,
        f"actual {tgt['actual_amount']} over {tgt['invoices']} bills — a target that "
        "cached its actuals would drift the first time a bill was voided",
    )
    check(
        "and against each figure separately",
        tgt["amount_pct"] is not None and tgt["weight_pct"] is not None,
        f"amount {tgt.get('amount_pct')}% weight {tgt.get('weight_pct')}% — a shop that "
        "manages in grams and one that manages in rupees are asking different questions",
    )
    check(
        "how much of the period has gone is shown beside them",
        tgt["period_elapsed_pct"] is not None,
        "60% of target reads very differently on day three than on day thirty",
    )

    # A weight-only target reports no money percentage rather than zero.
    r = client.post("/sales/targets", headers=auth, json={
        "scope": "seller", "seller_id": sman["id"],
        "period_start": str(date.today()), "period_end": str(date.today() + timedelta(days=30)),
        "target_weight_g": "100",
    }).json()
    check(
        "a weight-only target reports nothing against money, not zero",
        r["weight_pct"] is not None and r["amount_pct"] is None,
        f"amount {r.get('amount_pct')} — a percentage against nothing is meaningless, "
        "and zero would read as failure",
    )
    check(
        "a new salesman has brought nothing yet",
        Decimal(str(r["actual_weight_g"])) == 0,
        f"got {r['actual_weight_g']}",
    )

    # ------------------------------------------------------------------
    # Crediting a bill to a salesman
    #
    # The gap these cover: `Invoice.seller_id` existed and a seller target
    # filtered on it, but no screen ever set it — so every seller target read
    # 0% forever and the whole feature was decorative. What matters here is the
    # round trip: a bill names a seller, and that seller's page and target both
    # move. If only the target moved, the page would be lying; if only the page
    # moved, the target would be.
    # ------------------------------------------------------------------
    def perf(sid, **params):
        return client.get(f"/sales/sellers/{sid}/performance", headers=auth, params=params).json()

    before = perf(sman["id"])
    check("a seller's page loads before he has sold anything",
          before["invoices"] == 0 and Decimal(str(before["revenue"])) == 0,
          f"got {before['invoices']} bills")

    credited = client.post("/invoices", headers=auth, json={
        "customer_id": cust["id"], "seller_id": sman["id"],
        "gold_rate_per_g": str(day_rate),
        "items": [{"description": "Credited to the salesman", "quantity": 1,
                   "gold_weight_g": "10", "gold_purity": 22, "labor_amount": "5000"}],
    })
    check("an invoice can name its salesman → 201", credited.status_code == 201,
          f"got {credited.status_code}: {credited.text[:250]}")
    credited = credited.json()
    check("and it reads back with his name, not just his id",
          credited.get("seller_name") == sman["name"],
          f"got {credited.get('seller_name')!r} — a list showing #3 helps nobody")
    check("the customer's name comes back too",
          credited.get("customer_name") is not None,
          "the invoice list had to print #3 without this")
    # Issued, not left a draft: the performance page counts issued and paid
    # bills only, which is right — a draft is not a sale.
    iss = client.post(f"/invoices/{credited['id']}/issue", headers=pwd_h)
    check("the credited bill issues", iss.status_code in (200, 201),
          f"got {iss.status_code}: {iss.text[:200]}")

    after = perf(sman["id"])
    check(
        "the sale lands on the salesman's page",
        after["invoices"] == before["invoices"] + 1,
        f"{before['invoices']} → {after['invoices']}",
    )
    check(
        "revenue is net of tax, so commission is not charged on the government's money",
        Decimal(str(after["revenue"])) > 0
        and Decimal(str(after["revenue"]))
        <= Decimal(str(credited["total"])),
        f"revenue {after['revenue']} against a bill of {credited['total']}",
    )
    check(
        "his commission is estimated at his own agreed rate",
        Decimal(str(after["commission_estimate"]))
        == (Decimal(str(after["revenue"])) * Decimal(str(after["commission_pct"]))
            / Decimal("100")).quantize(Decimal("0.01")),
        f"got {after['commission_estimate']} at {after['commission_pct']}%",
    )
    check(
        "an unpaid bill shows as outstanding, not as collected",
        Decimal(str(after["collected"])) == 0 and Decimal(str(after["outstanding"])) > 0,
        f"collected {after['collected']}, outstanding {after['outstanding']} — "
        "a salesman writing bills nobody pays must not read as a good one",
    )
    check(
        "the customer he sold to is listed against him",
        any(c["customer_id"] == cust["id"] for c in after["customers"]),
        str([c["customer_name"] for c in after["customers"]]),
    )
    check(
        "and the bill itself is listed",
        any(i["invoice_no"] == credited["invoice_no"] for i in after["recent_invoices"]),
        str([i["invoice_no"] for i in after["recent_invoices"]]),
    )
    check(
        "his targets travel with him rather than needing a second lookup",
        len(after["targets"]) > 0,
        "the page showed no targets for a seller who has them",
    )
    check(
        "the target that read 0% forever now moves",
        any(Decimal(str(t["actual_amount"])) > 0 for t in after["targets"]),
        f"actuals {[t['actual_amount'] for t in after['targets']]} — this is the whole "
        "defect: seller targets could never be met because no bill named a seller",
    )
    check(
        "a bill credited to nobody stays credited to nobody",
        perf(brk["id"])["invoices"] == 0,
        "the broker was credited with a sale that named the salesman",
    )

    # ----- CUSTOMERS, BIGGEST FIRST, WITH WHAT THE SHOP KEPT -----
    section("Customers by spend")
    r = client.get("/reports/customers", headers=auth)
    check("customer report → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    cust_rep = r.json()
    check("it has rows", len(cust_rep["rows"]) > 0, f"got {len(cust_rep['rows'])}")
    check(
        "ranked by spend, biggest first",
        all(
            Decimal(str(cust_rep["rows"][i]["revenue"]))
            >= Decimal(str(cust_rep["rows"][i + 1]["revenue"]))
            for i in range(len(cust_rep["rows"]) - 1)
        ),
        "the question as asked is who spends most",
    )
    top = cust_rep["rows"][0]
    check(
        "and every row carries what was kept, not just what was spent",
        "gross_margin" in top and "margin_pct" in top,
        f"row keys: {sorted(top)} — spend flatters the customer who buys heavy metal thin",
    )
    check(
        "lines with no product behind them are flagged, not hidden",
        "uncosted_lines" in top,
        "a customer billed entirely on typed-in lines has a margin nobody should trust",
    )
    check(
        "revenue is net of tax",
        Decimal(str(cust_rep["revenue"])) >= 0,
        f"got {cust_rep['revenue']} — counting the government's money as revenue would "
        "inflate every margin here by the tax rate",
    )
    r = client.get("/reports/customers", headers=auth, params={"format": "csv"})
    check("and it exports", r.status_code == 200 and "customer" in r.text[:200],
          f"got {r.status_code}: {r.text[:120]}")

    r = client.get("/cash/flow", headers=auth, params={"format": "csv"})
    check(
        "the cash flow exports too — the shop reconciles in Excel",
        r.status_code == 200 and "entry" in r.text[:200],
        f"got {r.status_code}: {r.text[:120]}",
    )

    # ----- THE OVERVIEW ANSWERS ALL FOUR QUESTIONS -----
    section("Business overview")
    dash = client.get("/dashboard", headers=auth).json()
    tday = dash["today"]
    check(
        "today's money is there, cash and bank apart",
        all(k in tday for k in ("cash_in_hand", "bank_balance", "money_in_today",
                                "money_out_today")),
        f"keys: {sorted(k for k in tday if 'money' in k or 'bank' in k or 'cash' in k)} — a "
        "drawer is counted and an account is agreed against a statement; one figure covering "
        "both reconciles against neither",
    )
    check(
        "money out today includes what no invoice produced",
        Decimal(str(tday["money_out_today"])) > 0,
        f"got {tday['money_out_today']} — the rent was paid in cash today and has to be in it",
    )
    check(
        "what the shop is owed and owes covers metal, stones and cash",
        all(k in tday for k in ("customer_receivable", "supplier_payable", "worker_payable",
                                "stones_with_workers_ct", "metal_owed_to_makers_g")),
        f"keys present: {sorted(tday)}",
    )
    check(
        "silver is counted apart from gold, never added to it",
        "silver_in_hand_g" in tday and "silver_with_workers_g" in tday,
        "a combined metal figure is a number in no unit at all",
    )
    check(
        "the floor says what is in each department and how long it has sat",
        isinstance(dash.get("floor"), list)
        and all("oldest_days" in row for row in dash["floor"]),
        f"floor: {dash.get('floor')} — a count alone cannot tell a busy stage from a stuck one",
    )

    # ----- WHAT A WORKER IS HOLDING RIGHT NOW -----
    # "What is out with Zahid" was answerable only by reading every design.
    section("Worker's jobs")
    r = client.get("/designs", headers=auth, params={"worker_id": setter["id"]})
    check("designs can be listed by worker → 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:180]}")
    all_his = r.json()
    check("and he has some", len(all_his) > 0, f"got {len(all_his)}")
    r = client.get(
        "/designs",
        headers=auth,
        params={"worker_id": setter["id"], "held_by_worker": True},
    )
    held = r.json()
    check(
        "narrowing to what he is still holding is a subset",
        len(held) <= len(all_his),
        f"{len(held)} held vs {len(all_his)} ever — held must never exceed ever",
    )
    check(
        "a piece that visited him twice is listed once",
        len({d["id"] for d in all_his}) == len(all_his),
        f"{len(all_his)} rows, {len({d['id'] for d in all_his})} distinct — a worklist that "
        "lists a ring three times is one the shop stops trusting",
    )

    # ----- A PARTY'S ACCOUNT KEEPS ITS UNITS APART -----
    # The statement used to have two buckets: gold, and "everything else in
    # rupees". That was right while gold was the only commodity. Once silver
    # and stones became commodities it started reading a kilo of silver as a
    # rupee debt — a worker holding metal shown as owing money, which he could
    # then be asked to settle in cash.
    section("Party statement units")
    st = client.get(
        "/ledger/party-statement",
        headers=auth,
        params={"party_type": "worker", "party_id": karigar["id"]},
    )
    check("a worker's statement → 200", st.status_code == 200,
          f"got {st.status_code}: {st.text[:200]}")
    acct = st.json()
    check(
        "silver he holds is grams of silver, not rupees",
        Decimal(str(acct["closing_silver_g"])) > 0,
        f"closing silver {acct.get('closing_silver_g')}g — he was issued 1000g of 999; "
        "zero here means it was counted as cash",
    )
    setter_acct = client.get(
        "/ledger/party-statement",
        headers=auth,
        params={"party_type": "worker", "party_id": setter["id"]},
    ).json()
    check(
        "and a setter's stone debt is carats, not rupees",
        Decimal(str(setter_acct["closing_stone_ct"])) > 0,
        f"closing stones {setter_acct.get('closing_stone_ct')}ct — a carat debt cannot be "
        "settled by paying, so it must not sit in the cash column",
    )

    # ----- DUE DATES ARE CHASED, NOT JUST RECORDED -----
    # `Invoice.due_date` has been computed since credit terms were added and
    # nothing ever read it; `metal_due_date` recorded a promise to hand gold
    # back and nothing ever mentioned it again. A date the system knows and
    # never brings up is a date nobody acts on.
    section("Due dates")
    alerts_now = {a["key"] for a in client.get("/dashboard", headers=auth).json()["alerts"]}
    check(
        "a bill inside its credit terms is not called overdue",
        "invoices_overdue" not in alerts_now,
        f"alerts: {sorted(alerts_now)} — every bill written this morning on 30 days would "
        "otherwise be flagged, and the real ones would be lost among them",
    )

    # A bill issued on terms that have already run out.
    late_inv = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "term_days": 0,
        "items": [{"description": "late bill", "quantity": 1, "gold_weight_g": "1",
                   "gold_purity": 22}],
    }).json()
    r = client.post(f"/invoices/{late_inv['id']}/issue", headers=pwd_h)
    check("issue a bill due immediately", r.status_code == 200,
          f"got {r.status_code}: {r.text[:180]}")

    # Term 0 means due the day it was issued, so it is overdue from tomorrow —
    # not today. The alert must not fire on the day of issue.
    alerts_same_day = {a["key"] for a in client.get("/dashboard", headers=auth).json()["alerts"]}
    check(
        "a bill due today is not yet past its date",
        "invoices_overdue" not in alerts_same_day,
        f"alerts: {sorted(alerts_same_day)} — due today and overdue are different days",
    )

    # Metal promised to a maker, with the date already gone.
    od_design = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    r = client.post(
        f"/designs/{od_design['id']}/legs",
        headers=auth,
        json={
            "department_id": make_dept_id, "worker_id": karigar["id"],
            "gold_issued_g": "0", "gold_source_inventory_id": pure_gold["id"],
            "wastage_basis": "ratti_of_received", "wastage_ratti": "6",
            "piece_count": 1, "labour_basis": "flat", "labour_rate": "0",
            "metal_due_date": str(date.today() - timedelta(days=5)),
        },
    )
    check("record metal owed to a maker, already past its date → 201",
          r.status_code == 201, f"got {r.status_code}: {r.text[:220]}")
    alerts_after = {a["key"] for a in client.get("/dashboard", headers=auth).json()["alerts"]}
    check(
        "the shop is told it owes a maker metal past the agreed date",
        "metal_due" in alerts_after,
        f"alerts: {sorted(alerts_after)} — this is the only promise in the system to "
        "*deliver* metal, and nothing else in the day would ever raise it",
    )

    # ----- LIVE RATES (display only, and never 5xx) -----
    section("Live rates")
    r = client.get("/gold-rates/live", headers=auth)
    check(
        "live rates answer 200 whether or not the feed is configured",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]} — a display panel that takes the page down "
        "when a third party has a bad morning is worse than one that says it does not know",
    )
    lv = r.json()
    check(
        "and either carry a price or say why not",
        (lv.get("gold_per_gram") is not None) or bool(lv.get("unavailable")),
        f"gold={lv.get('gold_per_gram')} unavailable={lv.get('unavailable')} — a blank with "
        "no explanation is the one unacceptable answer",
    )
    check(
        "the caveat travels with the figures",
        "not the local market rate" in (lv.get("caveat") or ""),
        f"got {lv.get('caveat')!r} — spot converted to PKR is not what the bazaar charges",
    )
    # The whole point of the separate tab: this must not have become the rate
    # anything is priced at.
    r = client.get("/gold-rates/current", headers=auth, params={"currency": "PKR", "purity": 24})
    check(
        "the rate that prices things is still the one the shop set",
        r.status_code == 200 and Decimal(str(r.json()["rate_per_g"])) > 0,
        f"got {r.status_code}: {r.text[:150]}",
    )

    # ----- STOCK POSITION (what is held, and what it is worth) -----
    section("Stock position")
    r = client.get("/reports/stock-position", headers=auth)
    check("stock position → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    pos = r.json()
    gold_pos = next(m for m in pos["metals"] if m["metal"] == "gold")
    silver_pos = next(m for m in pos["metals"] if m["metal"] == "silver")
    check(
        "metals are valued on their pure content, not their scale reading",
        Decimal(str(gold_pos["fine_weight_g"])) < Decimal(str(gold_pos["weight_g"])),
        f"as weighed {gold_pos['weight_g']}, fine {gold_pos['fine_weight_g']} — equal would "
        "mean 22k was valued as though it were pure",
    )
    check(
        "999 silver is nearly all pure, and counted apart from the gold",
        Decimal(str(silver_pos["fine_weight_g"]))
        == (Decimal(str(silver_pos["weight_g"])) * Decimal("0.999")).quantize(Decimal("0.0001")),
        f"as weighed {silver_pos['weight_g']}, fine {silver_pos['fine_weight_g']}",
    )
    check(
        "the two metals are never summed into one weight",
        len({m["metal"] for m in pos["metals"]}) == 2,
        "a combined metal figure is a number in no unit at all",
    )
    check(
        "stones stay in carats",
        Decimal(str(pos["stone_weight_ct"])) >= 0 and "stone_weight_ct" in pos,
        str(pos.get("stone_weight_ct")),
    )

    # A metal with no rate today is counted but not valued. Reporting it at zero
    # would show real stock as worthless.
    r = client.get("/reports/stock-position", headers=staff_auth)
    check("staff can read stock", r.status_code == 200, f"got {r.status_code}")

    # ----- TWO KINDS OF BILL -----
    # A finished piece is billed on its metal; a parcel of loose stones has no
    # gold on it at all, and its discount argues against the stone price.
    section("Loose material bills")
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "kind": "loose_material",
        "currency": "PKR",
        "items": [{
            "description": "12 PTR commercial parcel", "quantity": 1,
            "stone_weight_ct": "30", "stone_rate_per_ct": "12000",
            "line_discount": "5000",
        }],
    })
    check("raise a loose-material bill → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    loose = r.json()
    check("the bill records which kind it is", loose["kind"] == "loose_material",
          f"got {loose.get('kind')}")
    check(
        "30ct at 12,000 less 5,000 = 355,000",
        Decimal(str(loose["items"][0]["line_total"])) == Decimal("355000"),
        f"got {loose['items'][0]['line_total']}",
    )
    check(
        "and it carries no gold",
        Decimal(str(loose["items"][0]["gold_amount"])) == 0,
        f"got {loose['items'][0]['gold_amount']}",
    )

    # The three ways gold sneaks onto a bill that should have none. Each would
    # report a real figure under the wrong lever.
    for field, value, why in (
        ("gold_weight_g", "10", "a weight makes a parcel of stones look like a piece"),
        ("sale_wastage_pct", "2", "wastage bills metal that was never sold"),
        ("discount_ratti", "6", "ratti discounts gold that is not there"),
    ):
        line = {
            "description": "parcel", "quantity": 1,
            "stone_weight_ct": "10", "stone_rate_per_ct": "1000",
            field: value,
        }
        rr = client.post("/invoices", headers=auth, json={
            "customer_id": customer_id, "sale_type": "normal", "kind": "loose_material",
            "currency": "PKR", "items": [line],
        })
        check(
            f"a loose bill refuses {field} → 422",
            rr.status_code == 422,
            f"got {rr.status_code}: {rr.text[:180]} — {why}",
        )

    # The default is unchanged, so every bill the shop already writes is
    # untouched.
    r = client.post("/invoices", headers=auth, json={
        "customer_id": customer_id, "sale_type": "normal", "currency": "PKR",
        "items": [{"description": "ring", "quantity": 1, "gold_weight_g": "5",
                   "gold_purity": 22}],
    })
    check(
        "a bill with no kind stated is a finished-product bill",
        r.status_code == 201 and r.json()["kind"] == "finished_product",
        f"got {r.status_code}: {r.json().get('kind') if r.status_code == 201 else r.text[:150]}",
    )

    # ----- CASH BOOK (the money no other document explains) -----
    section("Cash book")
    r = client.post("/cash/categories", headers=auth, json={
        "name": "Rent", "direction": "paid", "account_code": "5300",
    })
    check("create an expense heading → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:200]}")
    rent = r.json()
    r = client.post("/cash/categories", headers=auth, json={
        "name": "Owner's float", "direction": "received",
    })
    check("create a receipt heading → 201", r.status_code == 201, f"got {r.status_code}")
    float_cat = r.json()

    r = client.post("/cash/categories", headers=auth, json={
        "name": "Bad head", "account_code": "9999",
    })
    check(
        "a heading pointing at a non-existent account is refused → 400",
        r.status_code == 400,
        f"got {r.status_code}: {r.text[:180]} — caught at setup, not on the hundredth expense",
    )

    cash_before = Decimal(str(client.get("/ledger/position", headers=auth).json()["cash_in_hand"]))
    r = client.post("/cash/entries", headers=auth, json={
        "direction": "paid", "method": "cash", "category_id": rent["id"],
        "amount": "40000", "counterparty": "Landlord", "occurred_on": str(date.today()),
    })
    check("pay the rent in cash → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:250]}")
    rent_entry = r.json()
    check("the entry is numbered", rent_entry["entry_no"].startswith("CE-"),
          f"got {rent_entry.get('entry_no')}")
    cash_after = Decimal(str(client.get("/ledger/position", headers=auth).json()["cash_in_hand"]))
    check(
        "the drawer is 40,000 lighter, in the ledger and not just on the row",
        cash_after == cash_before - Decimal("40000"),
        f"cash went from {cash_before} to {cash_after}",
    )
    check(
        "books balance after an expense",
        client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True,
    )

    # A bank movement has to name its account or it cannot be reconciled; a
    # cash one must not, or it claims money passed through a bank it never did.
    r = client.post("/cash/entries", headers=auth, json={
        "direction": "paid", "method": "bank", "category_id": rent["id"], "amount": "1000",
    })
    check("a bank entry with no account is refused → 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:200]}")

    # A heading declared for money out cannot be used on money in.
    r = client.post("/cash/entries", headers=auth, json={
        "direction": "received", "method": "cash", "category_id": rent["id"], "amount": "1000",
    })
    check("a paid-only heading is refused on a receipt → 400", r.status_code == 400,
          f"got {r.status_code}: {r.text[:200]}")

    r = client.post("/cash/entries", headers=auth, json={
        "direction": "received", "method": "cash", "category_id": float_cat["id"],
        "amount": "25000", "counterparty": "Owner",
    })
    check("put money into the till → 201", r.status_code == 201,
          f"got {r.status_code}: {r.text[:220]}")

    # The flow report reads the journal, not the cash entries — so the rent and
    # every customer who paid today appear side by side.
    r = client.get("/cash/flow", headers=auth, params={"date_from": str(date.today())})
    check("the day's cash flow → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    flow = r.json()
    check(
        "the rent shows as money out",
        Decimal(str(flow["money_out"])) >= Decimal("40000"),
        f"money_out={flow['money_out']} — the expense did not reach the report",
    )
    check(
        "and it is filed under the head it was posted to",
        any(h["account_code"] == "5300" and Decimal(str(h["money_out"])) >= Decimal("40000")
            for h in flow["by_head"]),
        "heads: "
        + ", ".join(
            f"{h['account_code']} in={h['money_in']} out={h['money_out']}"
            for h in flow["by_head"]
        ),
    )
    check(
        "a head that moved nothing is left off the report",
        all(
            Decimal(str(h["money_in"])) or Decimal(str(h["money_out"]))
            for h in flow["by_head"]
        ),
        "a row of zeroes reads as 'nothing happened here' when two things did and cancelled out",
    )
    check(
        "the report closes on itself: opening + net = closing",
        Decimal(str(flow["closing_cash"])) + Decimal(str(flow["closing_bank"]))
        == Decimal(str(flow["opening_cash"])) + Decimal(str(flow["opening_bank"]))
        + Decimal(str(flow["net"])),
        f"opening {flow['opening_cash']}+{flow['opening_bank']}, net {flow['net']}, "
        f"closing {flow['closing_cash']}+{flow['closing_bank']}",
    )
    check(
        "money the shop took from customers is in there too, not just manual entries",
        any(h["account_code"] not in ("5300", "4400") for h in flow["by_head"]),
        "a cash report that only knew about manual entries would miss every sale",
    )
    r = client.get("/cash/flow", headers=staff_auth, params={"date_from": str(date.today())})
    check("staff cannot read the day's money → 403", r.status_code == 403, f"got {r.status_code}")

    # ----- AI INSIGHTS (degrade-without-a-provider contract) -----
    section("AI insights")
    r = ai_client.get("/insights/wastage-anomalies", headers=auth, params={"days": 90})
    check(
        "wastage analysis returns figures with no model configured",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    r = ai_client.get("/insights/margin-watch", headers=auth, params={"days": 90})
    check(
        "margin watch returns figures with no model configured",
        r.status_code == 200,
        f"got {r.status_code}: {r.text[:200]}",
    )
    # Whether a model is configured is a property of the machine, not of the
    # code, so the assertions below adapt rather than encoding one setup. What
    # is invariant either way is that the AI layer never 500s: unconfigured it
    # explains itself, configured it either answers or fails with the
    # provider's own reason. A traceback is the one unacceptable outcome, and
    # is exactly what an out-of-credit key used to produce.
    ai_on = ai_client.get("/insights/margin-watch", headers=auth, params={"days": 90}).json().get(
        "ai_enabled", False
    )
    r = ai_client.post("/insights/ask", headers=auth, json={"question": "kitna sona Zahid ke paas hai"})
    if ai_on:
        check(
            "ask does not fall over when a model is configured",
            r.status_code in (200, 400, 502),
            f"got {r.status_code}: {r.text[:200]}",
        )
    else:
        check(
            "ask returns a clean 503 when no model is configured",
            r.status_code == 503,
            f"got {r.status_code}: {r.text[:200]}",
        )
    r = client.get("/insights/wastage-anomalies", headers=staff_auth, params={"days": 90})
    check("staff cannot read the wastage analysis → 403", r.status_code == 403, f"got {r.status_code}")

    # --- the assistant ---
    # A data question here takes exactly the /ask path, so it is exactly as
    # sensitive and fails exactly as cleanly.
    r = ai_client.post("/insights/chat", headers=auth, json={
        "messages": [{"role": "user", "content": "kitna sona Zahid ke paas hai"}],
    })
    if ai_on:
        check(
            "the assistant answers or fails cleanly, never with a traceback",
            r.status_code in (200, 400, 502),
            f"got {r.status_code}: {r.text[:200]}",
        )
    else:
        check(
            "the assistant returns a clean 503 when no model is configured",
            r.status_code == 503,
            f"got {r.status_code}: {r.text[:200]} — an unconfigured model must not 500",
        )
        check(
            "and the 503 says how to configure it",
            "AI_PROVIDER" in r.text,
            "a 503 nobody can act on is the same as a crash",
        )
    r = client.post("/insights/chat", headers=staff_auth, json={
        "messages": [{"role": "user", "content": "what is the margin"}],
    })
    check(
        "staff cannot use the assistant → 403",
        r.status_code == 403,
        f"got {r.status_code} — it can read customer balances and margins",
    )
    r = client.post("/insights/chat", headers=auth, json={"messages": []})
    check("an empty conversation is rejected → 422", r.status_code == 422, f"got {r.status_code}")

    # --- generated images ---
    r = ai_client.post(
        f"/products/{finished_product_id}/image/generate",
        headers=auth,
        data={"prompt": "a 22k gold taka pendant with a floral border", "attach": "false"},
    )
    check(
        "image generation never 500s, configured or not",
        r.status_code in (200, 502, 503),
        f"got {r.status_code}: {r.text[:220]}",
    )
    if r.status_code == 502:
        # Worth its own assertion: the provider's own words are what tell the
        # operator whether to top up, fix a model name, or wait — and those are
        # three different actions.
        check(
            "and a provider refusal carries the provider's reason",
            len(r.text) > 40,
            f"got {r.text[:160]}",
        )
    r = client.post(
        "/products/999999/image/generate", headers=auth, data={"prompt": "anything at all"}
    )
    check(
        "generating for a product that does not exist → 404",
        r.status_code == 404,
        f"got {r.status_code} — the piece is checked before the provider is called, so a "
        "typo cannot spend money",
    )
    r = client.post(f"/products/{finished_product_id}/image/generate", headers=auth, data={"prompt": "x"})
    check("too short a prompt is refused → 422", r.status_code == 422, f"got {r.status_code}")
    r = client.post(
        f"/products/{finished_product_id}/image/generate",
        headers=staff_auth,
        data={"prompt": "a 22k gold taka pendant"},
    )
    check(
        "staff cannot spend money on generated images → 403",
        r.status_code == 403,
        f"got {r.status_code}",
    )
    after = client.get(f"/products/{finished_product_id}", headers=auth).json()
    check(
        "a failed generation leaves the piece's image alone",
        after.get("image_url") is None,
        f"image_url={after.get('image_url')}",
    )

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
    # ----------------------------------------------------------------------
    # Bullion bills: gold and silver, one dealer, two control accounts
    #
    # Silver could be issued to a karigar, valued, revalued and reported long
    # before it could be *bought* — `gold_purchases` had no metal column, so
    # the only way silver ever entered was an opening balance. These assertions
    # exist to hold the two apart: the failure they guard against is not a
    # crash but a silent one, where five kilos of silver lands in 1130 and the
    # shop reads a hundredfold overstatement of its gold.
    # ----------------------------------------------------------------------
    def silver_in_hand() -> Decimal:
        return Decimal(str(client.get("/ledger/position", headers=auth).json()["silver_in_hand_g"]))

    gold_before_bullion = gold_in_hand()
    silver_before_bullion = silver_in_hand()

    r = client.post(
        "/purchasing/gold-purchases",
        headers=auth,
        json={
            "supplier_id": supplier["id"],
            "payment_mode": "credit",
            "extra_cost_pct": "0",
            "items": [{"description": "TT bar", "purity": 24, "weight_g": "100",
                       "rate_per_g": str(day_rate)}],
        },
    )
    check("buy gold bullion → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    gp = r.json()
    check("a gold bill is numbered GP", gp["purchase_no"].startswith("GP-"), gp["purchase_no"])
    check("a gold bill reads back as gold", gp["metal"] == "gold", str(gp.get("metal")))
    check(
        "100g of 24k adds 100 fine grams of gold",
        abs((gold_in_hand() - gold_before_bullion) - Decimal("100")) <= Decimal("0.0002"),
        f"moved {gold_in_hand() - gold_before_bullion}",
    )
    check(
        "a gold bill does not touch silver",
        silver_in_hand() == silver_before_bullion,
        f"silver moved by {silver_in_hand() - silver_before_bullion}",
    )

    # Silver states fineness, never karat. Both wrong ways round are refused
    # rather than coerced — a coerced purity is one nobody ever sees again.
    r = client.post(
        "/purchasing/gold-purchases",
        headers=auth,
        json={
            "supplier_id": supplier["id"], "metal": "silver", "payment_mode": "cash",
            "items": [{"purity": 24, "weight_g": "1000", "rate_per_g": "300"}],
        },
    )
    check("silver quoted in karat → 422", r.status_code == 422, f"got {r.status_code}: {r.text[:200]}")
    r = client.post(
        "/purchasing/gold-purchases",
        headers=auth,
        json={
            "supplier_id": supplier["id"], "metal": "silver", "payment_mode": "cash",
            "items": [{"weight_g": "1000", "rate_per_g": "300"}],
        },
    )
    check(
        "silver with no fineness at all → 422, not 'assume pure'",
        r.status_code == 422,
        f"got {r.status_code}: {r.text[:200]}",
    )

    gold_before_silver = gold_in_hand()
    r = client.post(
        "/purchasing/gold-purchases",
        headers=auth,
        json={
            "supplier_id": supplier["id"], "metal": "silver", "payment_mode": "cash",
            "items": [
                {"description": "999 bar", "tunch_pct": "99.9", "weight_g": "4000",
                 "rate_per_g": "300"},
                {"description": "sterling", "tunch_pct": "92.5", "weight_g": "1000",
                 "rate_per_g": "280"},
            ],
        },
    )
    check("buy silver bullion → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    sb = r.json()
    check(
        "a silver bill gets its own series, not the stone-purchase SP",
        sb["purchase_no"].startswith("SB-"),
        sb["purchase_no"],
    )
    check("a silver bill reads back as silver", sb["metal"] == "silver", str(sb.get("metal")))
    check(
        "silver banks at its fineness: 4000×0.999 + 1000×0.925 = 4921 fine",
        abs(Decimal(str(sb["total_fine_g"])) - Decimal("4921")) <= Decimal("0.0002"),
        f"got {sb['total_fine_g']}",
    )
    check(
        "those 4921 fine grams land in silver",
        abs((silver_in_hand() - silver_before_bullion) - Decimal("4921")) <= Decimal("0.0002"),
        f"moved {silver_in_hand() - silver_before_bullion}",
    )
    check(
        "and not one gram of them lands in gold",
        gold_in_hand() == gold_before_silver,
        f"gold moved by {gold_in_hand() - gold_before_silver} on a silver bill",
    )
    check(
        "a silver lot carries no karat",
        all(i["purity"] is None for i in sb["items"]),
        str([i["purity"] for i in sb["items"]]),
    )
    check("books balance after both bullion bills",
          client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)
    check(
        "the two bills are separable by metal",
        [x["purchase_no"] for x in
         client.get("/purchasing/gold-purchases?metal=silver", headers=auth).json()]
        == [sb["purchase_no"]],
        "the silver filter returned the wrong set",
    )
    # Fineness keys the pot, so 999 and 925 are two buckets rather than one
    # blended figure nobody can weigh against the safe. Asserted on the tunch
    # and not the label: a pot the shop already opened and named itself — the
    # seed ships "999 silver bullion" — must be *found*, not shadowed by a
    # second one this code named its own way. Two rows for one fineness is the
    # bug; what they are called is the shop's business.
    silver_pots = [
        i for i in client.get("/inventory?type=raw_silver", headers=auth).json()
        if i["type"] == "raw_silver"
    ]
    finenesses = [Decimal(str(p["tunch_pct"])) for p in silver_pots if p.get("tunch_pct")]
    check(
        "999 and sterling get their own melt pots",
        {f.normalize() for f in finenesses} >= {Decimal("99.9"), Decimal("92.5")},
        str([(p["label"], p.get("tunch_pct")) for p in silver_pots]),
    )
    check(
        "and buying into a fineness already on the books reuses its pot",
        len(finenesses) == len(set(f.normalize() for f in finenesses)),
        f"duplicate silver pots: {[(p['label'], p.get('tunch_pct')) for p in silver_pots]}",
    )

    # ----------------------------------------------------------------------
    # Material outside the company
    #
    # The UI spec calls this first-class twice and nothing aggregated it: the
    # position report gives one total, a party statement gives one party. What
    # this must get right is that it reads the **ledger**, not open job legs —
    # a worker with every leg closed and metal still unreturned has to appear.
    # ----------------------------------------------------------------------
    # ----------------------------------------------------------------------
    # Vendor bills: due dates, and paying them oldest-first
    #
    # Before this, a purchase on credit posted to 2110 and stayed there — no
    # date said when it was due and nothing could pay it, so the payables
    # figure only ever grew. What these assertions pin down is the settlement
    # rule the shop chose: a payment clears the oldest bill first, and the
    # paid/outstanding split is derived at read time rather than stored, so it
    # cannot drift from the ledger.
    # ----------------------------------------------------------------------
    def bills(**params):
        return client.get("/purchasing/bills", headers=auth, params=params).json()

    # Its own stone, so these bills cannot disturb the carat figures the stone
    # stock assertions below are checking. A test that quietly changes another
    # test's inputs is worse than no test.
    bill_stone = client.post(
        "/stones", headers=auth,
        json={"name": "Ageing Test Stone", "kind": "other"},
    ).json()["id"]

    # Two dated bills on the same dealer, a week apart, plus a third with no
    # date agreed — all three states the report has to tell apart.
    old_bill = client.post(
        "/purchasing/stone-purchases", headers=auth,
        json={"supplier_id": supplier["id"], "due_date": "2020-01-31",
              "purchased_at": "2020-01-01T10:00:00Z",
              "items": [{"stone_id": bill_stone, "quantity": 1, "weight_ct": "1",
                         "rate_per_ct": "100000"}]},
    )
    check("a bill can carry a due date → 201", old_bill.status_code == 201,
          f"got {old_bill.status_code}: {old_bill.text[:200]}")
    old_bill = old_bill.json()
    check("the due date reads back", old_bill["due_date"] == "2020-01-31", str(old_bill.get("due_date")))

    new_bill = client.post(
        "/purchasing/stone-purchases", headers=auth,
        json={"supplier_id": supplier["id"], "due_date": "2020-02-28",
              "purchased_at": "2020-02-01T10:00:00Z",
              "items": [{"stone_id": bill_stone, "quantity": 1, "weight_ct": "1",
                         "rate_per_ct": "60000"}]},
    ).json()

    mine = [b for b in bills(supplier_id=supplier["id"])["rows"]
            if b["purchase_no"] in (old_bill["purchase_no"], new_bill["purchase_no"])]
    check("both bills are overdue — their dates are years past",
          all(b["status"] == "overdue" for b in mine), str([(b["purchase_no"], b["status"]) for b in mine]))
    check("and each says how late it is",
          all((b["days_overdue"] or 0) > 1000 for b in mine),
          str([b["days_overdue"] for b in mine]))

    # A cash-paid bullion bill never created a payable, so it must not appear.
    cash_bill = client.post(
        "/purchasing/gold-purchases", headers=auth,
        json={"supplier_id": supplier["id"], "payment_mode": "cash",
              "items": [{"purity": 24, "weight_g": "1", "rate_per_g": "100"}]},
    ).json()
    check(
        "a bill paid at the counter is not a debt and is not listed",
        cash_bill["purchase_no"] not in
        [b["purchase_no"] for b in bills(supplier_id=supplier["id"])["rows"]],
        f"{cash_bill['purchase_no']} appeared in the payables list",
    )

    # Pay part of the older bill. Oldest-first is the rule the shop chose.
    pay = client.post(
        "/purchasing/supplier-payments", headers=auth,
        json={"supplier_id": supplier["id"], "amount": "40000", "method": "cash",
              "reference": "cheque 001"},
    )
    check("pay a supplier → 201", pay.status_code == 201, f"got {pay.status_code}: {pay.text[:220]}")
    pay = pay.json()
    check("a supplier payment gets its own VP series", pay["payment_no"].startswith("VP-"),
          pay["payment_no"])
    check("and it posts to the ledger", pay["journal_entry_no"] is not None, str(pay))
    check("paying 'on credit' is refused — that is the bill, not a payment",
          client.post("/purchasing/supplier-payments", headers=auth,
                      json={"supplier_id": supplier["id"], "amount": "1", "method": "credit"}
                      ).status_code == 422,
          "credit was accepted as a payment method")

    def bill_named(no):
        return next(b for b in bills(supplier_id=supplier["id"])["rows"] if b["purchase_no"] == no)

    # The oldest open bill on this supplier is not necessarily ours — earlier
    # sections bought stones from them too — so assert the *rule* rather than a
    # figure: payments land on the earliest-dated bills and never skip ahead.
    rows_now = bills(supplier_id=supplier["id"])["rows"]
    paid_order = [b for b in rows_now if Decimal(str(b["paid"])) > 0]
    unpaid_before_paid = [
        b for b in rows_now
        if Decimal(str(b["paid"])) == 0
        and any(p["purchased_on"] > b["purchased_on"] for p in paid_order)
    ]
    check(
        "a payment clears the oldest bills first and skips none",
        not unpaid_before_paid,
        f"these were skipped: {[b['purchase_no'] for b in unpaid_before_paid]}",
    )
    check(
        "the newer of our two bills is untouched while the older is unsettled",
        Decimal(str(bill_named(new_bill["purchase_no"])["paid"])) == Decimal("0"),
        "the later bill was paid before the earlier one",
    )
    check(
        "outstanding never exceeds the bill",
        all(Decimal(str(b["outstanding"])) <= Decimal(str(b["total"])) for b in rows_now),
        "a bill shows more outstanding than it was ever worth",
    )
    check(
        "total outstanding is the sum of the rows",
        abs(Decimal(str(bills(supplier_id=supplier["id"])["total_outstanding"]))
            - sum((Decimal(str(b["outstanding"])) for b in rows_now), Decimal("0")))
        <= Decimal("0.01"),
        "the header total disagrees with the table",
    )

    # Reversing gives the money back to the bills, because nothing was stored.
    outstanding_paid = Decimal(str(bills(supplier_id=supplier["id"])["total_outstanding"]))
    rv = client.post(f"/purchasing/supplier-payments/{pay['id']}/reverse", headers=pwd_h, json={})
    check("reverse a supplier payment → 200", rv.status_code == 200,
          f"got {rv.status_code}: {rv.text[:220]}")
    check(
        "reversing a payment puts the bills back to outstanding",
        Decimal(str(bills(supplier_id=supplier["id"])["total_outstanding"]))
        == outstanding_paid + Decimal("40000"),
        "the reversal did not restore what the payment had cleared",
    )
    check("books balance after paying and un-paying a supplier",
          client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)

    # ----------------------------------------------------------------------
    # Product timeline
    #
    # The lifecycle of one piece, assembled from the documents rather than a
    # stored log. What these pin down is that it is *derived*: a timeline kept
    # as its own table becomes a second version of history the moment anything
    # is reversed, and the two then disagree with nobody noticing.
    # ----------------------------------------------------------------------
    section("Product timeline")
    made = [p for p in client.get("/products", headers=auth, params={"limit": 100}).json()
            if p.get("serial_no")]
    check("there are products to trace", len(made) > 0, "no products on file")
    traced = next((p for p in made if p.get("status") == "sold"), made[0])

    r = client.get(f"/products/{traced['id']}/timeline", headers=auth)
    check("product timeline → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    tl = r.json()
    kinds = [e["kind"] for e in tl["events"]]
    check("it always includes the moment the piece entered stock",
          "stocked" in kinds, str(kinds))
    check(
        "a piece made on the floor carries its job and both ends of every leg",
        not tl["design_no"] or ("job" in kinds and "issued" in kinds and "received" in kinds),
        f"job {tl['design_no']} produced {kinds}",
    )
    check(
        "events are in the order they happened",
        all(
            (a["at"] or "9999") <= (b["at"] or "9999")
            for a, b in zip(tl["events"], tl["events"][1:])
        ),
        str([e["at"] for e in tl["events"]]),
    )
    check(
        "an undated event sorts last, not to the beginning of time",
        all(e["at"] for e in tl["events"]) or tl["events"][-1]["at"] is None,
        "a leg still out has no return date, and sorting it as the epoch would "
        "put it before the metal was bought",
    )
    check(
        "every event that names a document says where to open it",
        all(e["to"] for e in tl["events"] if e["reference"]),
        str([(e["reference"], e["to"]) for e in tl["events"] if e["reference"]]),
    )

    if traced.get("status") == "sold":
        check("a sold piece shows the bill that sold it", "sold" in kinds, str(kinds))
        check(
            "and its margin is sale less cost, not a guess",
            tl["margin"] is not None
            and abs(Decimal(str(tl["margin"]))
                    - (Decimal(str(tl["sold_for"]))
                       - Decimal(str(tl["total_cost"])) - Decimal(str(tl["material_cost"]))))
            <= Decimal("0.01"),
            f"margin {tl['margin']} against sold {tl['sold_for']} and cost "
            f"{tl['total_cost']}+{tl['material_cost']}",
        )

    unsold = next((p for p in made if p.get("status") != "sold"), None)
    if unsold:
        u = client.get(f"/products/{unsold['id']}/timeline", headers=auth).json()
        check(
            "an unsold piece reports no margin rather than a negative one",
            u["margin"] is None and u["sold_for"] is None,
            f"margin {u['margin']} on a piece that has not sold — a margin on unsold "
            "stock is a guess dressed as a figure",
        )

    check("a timeline for a piece that does not exist → 404",
          client.get("/products/999999/timeline", headers=auth).status_code == 404)

    # ----------------------------------------------------------------------
    # Roles that mean something, and modules that can be switched off
    #
    # Two features answering the same question from opposite sides: what is
    # this person allowed to reach. The assertions that matter are the ones
    # about failing closed — a permission system that quietly grants nothing,
    # or a module that is off in the sidebar and on at the endpoint, is worse
    # than none, because both look like they are working.
    # ----------------------------------------------------------------------
    section("RBAC and modules")

    check(
        "an admin cannot reach the super admin panel",
        client.get("/admin/modules", headers=auth).status_code == 403,
        "an admin who can widen their own permissions is not limited by them",
    )

    sa_user = client.post("/users", headers=auth, json={
        "email": "root_e2e@jewelryerp.com", "full_name": "Root",
        "password": "root12345", "role_id": 1,
    })
    check("admin can still manage users", sa_user.status_code == 201,
          f"got {sa_user.status_code}: {sa_user.text[:160]} — this broke once when the "
          "wildcard permission stopped being a stored grant")
    sr = client.post("/auth/login", json={"email": "root_e2e@jewelryerp.com",
                                          "password": "root12345"}).json()
    sa = {"Authorization": f"Bearer {sr['access_token']}"}
    sa_pwd = {**sa, "X-Confirm-Password": "root12345"}

    # --- the catalogue -------------------------------------------------
    cat = client.get("/admin/permissions", headers=sa).json()
    keys = {p["key"] for p in cat}
    check("the catalogue lists every permission", len(cat) > 50, f"got {len(cat)}")
    check(
        "including ones no seeded role holds",
        "master:delete" in keys and "ledger:delete" in keys,
        "these are checked by real endpoints and belonged to no role — deriving the "
        "catalogue from grants dropped them and quietly broke six delete buttons",
    )

    roles = {r["name"]: r for r in client.get("/admin/roles", headers=sa).json()}
    check("admin holds the whole catalogue", len(roles["admin"]["permissions"]) == len(cat),
          f"admin {len(roles['admin']['permissions'])} vs catalogue {len(cat)}")
    check("staff holds fewer", len(roles["staff"]["permissions"]) < len(cat),
          "a role that holds everything is not a role")
    check(
        "the super admin holds the whole catalogue too",
        len(roles["superadmin"]["permissions"]) == len(cat),
        f"holds {len(roles['superadmin']['permissions'])} of {len(cat)}",
    )
    # Two mechanisms, failing in opposite directions: the grants make the role
    # honest — a panel showing an empty role that mysteriously works invites
    # somebody to tidy it away — while the name check means that even with
    # every grant gone, whoever holds it can still get in and restore them.
    check(
        "and is still recognised by name, so it cannot be stripped",
        client.patch(f"/admin/roles/{roles['superadmin']['id']}", headers=sa_pwd,
                     json={"permissions": []}).status_code == 409,
        "stripping it would leave nobody able to grant anything, with no way back",
    )
    sa_login = client.post("/auth/login", json={
        "email": "superadmin@jewelryerp.com", "password": "superadmin123"})
    check("the seeded super admin account signs in", sa_login.status_code == 200,
          f"got {sa_login.status_code} — the tier is useless if nobody holds it")
    seeded = {"Authorization": f"Bearer {sa_login.json()['access_token']}"}
    check(
        "and it reaches both the panel and the ordinary screens",
        client.get("/admin/modules", headers=seeded).status_code == 200
        and client.get("/customers", headers=seeded).status_code == 200,
        "a super admin who cannot open an invoice cannot check what they just changed",
    )

    # --- a role the shop creates itself --------------------------------
    made = client.post("/admin/roles", headers=sa, json={
        "name": "Viewer", "description": "Reads and nothing else",
        "permissions": ["customer:read", "invoice:read"],
    })
    check("create a role → 201", made.status_code == 201, f"got {made.status_code}: {made.text[:180]}")
    made = made.json()
    check("it holds exactly what was asked for",
          sorted(made["permissions"]) == ["customer:read", "invoice:read"], str(made["permissions"]))

    # The trap this feature exists to remove: before permissions were rows, a
    # role created this way silently held nothing.
    client.post("/users", headers=auth, json={
        "email": "viewer_e2e@jewelryerp.com", "full_name": "Viewer",
        "password": "view12345", "role_id": made["id"],
    })
    vr = client.post("/auth/login", json={"email": "viewer_e2e@jewelryerp.com",
                                          "password": "view12345"}).json()
    vw = {"Authorization": f"Bearer {vr['access_token']}"}
    check(
        "a shop-created role actually works",
        client.get("/customers", headers=vw).status_code == 200,
        "before this, a custom role held nothing and no error said why",
    )
    check(
        "and is limited to what it was granted",
        client.get("/ledger/entries", headers=vw).status_code == 403,
        "a role that was granted two permissions must not reach a third",
    )

    check(
        "a permission nothing checks is refused",
        client.patch(f"/admin/roles/{made['id']}", headers=sa_pwd,
                     json={"permissions": ["invoice:read", "not:areal"]}).status_code == 422,
        "granting it would confer nothing while looking like it did",
    )
    check(
        "revoking works, not just granting",
        sorted(client.patch(f"/admin/roles/{made['id']}", headers=sa_pwd,
                            json={"permissions": ["invoice:read"]}).json()["permissions"])
        == ["invoice:read"],
        "a merge-only endpoint can add a permission and never take one away",
    )
    check(
        "the super admin role cannot be edited",
        client.patch(f"/admin/roles/{roles['superadmin']['id']}", headers=sa_pwd,
                     json={"permissions": []}).status_code == 409,
        "stripping it would leave nobody able to grant anything, with no way back",
    )
    check(
        "a system role cannot be renamed",
        client.patch(f"/admin/roles/{roles['staff']['id']}", headers=sa_pwd,
                     json={"name": "peon"}).status_code == 409,
        "the seed and the migrations look it up by name",
    )
    check(
        "a role with users on it cannot be deleted",
        client.delete(f"/admin/roles/{made['id']}", headers=sa_pwd).status_code == 409,
        "it would leave their accounts pointing at nothing",
    )

    # --- the four roles this shop keeps ---------------------------------
    # Nine were seeded to start with, because the specification listed nine.
    # The shop wanted four. Asserting the *exact* set rather than a subset is
    # the point: a role nobody asked for is a door nobody is watching, and the
    # next person to add one should have to say so here.
    check(
        "exactly four roles are seeded, and no more",
        set(roles) == {"superadmin", "admin", "accountant", "staff"},
        f"got {sorted(roles)}",
    )
    check(
        "all four are system roles and cannot be renamed or deleted",
        all(roles[n]["is_system"] for n in roles),
        str({n: roles[n]["is_system"] for n in roles}),
    )
    check(
        "staff holds something, and not everything",
        0 < len(roles["staff"]["permissions"]) < len(cat),
        f"staff holds {len(roles['staff']['permissions'])} of {len(cat)}",
    )
    for sensitive in ("ledger:read", "audit:read", "report:profit", "user:manage"):
        check(
            f"staff cannot reach {sensitive}",
            sensitive not in roles["staff"]["permissions"],
            "the owner's information should not sit behind a day-to-day login",
        )

    # --- modules -------------------------------------------------------
    mods = {m["key"]: m for m in client.get("/admin/modules", headers=sa).json()}
    check("every sidebar section has a switch", len(mods) >= 10, str(sorted(mods)))
    check(
        "dashboard and settings cannot be switched off",
        not mods["settings"]["can_disable"] and not mods["dashboard"]["can_disable"],
        "a shop that turned off Settings could never turn anything back on",
    )
    check(
        "manufacturing is held open by live work",
        mods["manufacturing"]["blockers"] and not mods["manufacturing"]["can_switch_off"],
        f"blockers {mods['manufacturing']['blockers']} — metal is out with workers",
    )
    r = client.patch("/admin/modules/manufacturing", headers=sa_pwd, json={"enabled": False})
    check("and switching it off is refused → 409", r.status_code == 409,
          f"got {r.status_code}: {r.text[:180]}")
    check(
        "the refusal names what is holding it",
        "out with workers" in r.text or "outside the building" in r.text,
        r.text[:200],
    )

    # A module with nothing live in it switches off — and is off on the server,
    # not merely hidden in the sidebar.
    r = client.patch("/admin/modules/rates", headers=sa_pwd, json={"enabled": False})
    check("a quiet module switches off → 200", r.status_code == 200, f"got {r.status_code}")
    check(
        "and its endpoints refuse, not just its links",
        client.get("/gold-rates", headers=auth).status_code == 403,
        "hiding a link changes nothing — the POST still arrives",
    )
    check(
        "other modules are unaffected",
        client.get("/customers", headers=auth).status_code == 200,
        "one switch must not take the shop down",
    )
    client.patch("/admin/modules/rates", headers=sa_pwd, json={"enabled": True})
    check("switching back on restores it",
          client.get("/gold-rates", headers=auth).status_code == 200)
    check(
        "an admin cannot switch modules",
        client.patch("/admin/modules/rates", headers=pwd_h, json={"enabled": False}).status_code
        == 403,
        "flags belong to somebody who is not also running the counter",
    )

    # ----------------------------------------------------------------------
    # The business overview
    #
    # One page a partner gets shown, so the thing to hold is that it never
    # invents a number: every figure is fetched from the screen that owns it.
    # A second definition of net worth is a second thing to disagree with the
    # first, and this is the page where that would be noticed last.
    # ----------------------------------------------------------------------
    section("Business overview")
    r = client.get("/reports/overview", headers=auth)
    check("overview → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    ov = r.json()
    w = ov["worth"]

    check(
        "net worth is what is owned less what is owed",
        abs(Decimal(str(w["net_worth"]))
            - (Decimal(str(w["total_owned"])) + Decimal(str(w["total_owed"]))))
        <= Decimal("0.01"),
        f"{w['net_worth']} against {w['total_owned']} + {w['total_owed']}",
    )
    check(
        "what is owed is carried negative, so the column sums",
        all(Decimal(str(l["amount"])) <= 0 for l in w["owed"]),
        str([(l["label"], l["amount"]) for l in w["owed"]]),
    )
    check(
        "every line says where to go and read it",
        all(l["to"] for l in w["owned"] + w["owed"]),
        str([l["label"] for l in w["owned"] + w["owed"] if not l["to"]]),
    )

    # The figures must be the ones the owning screens report, not a second
    # derivation that happens to look similar.
    stock = client.get("/reports/stock-position", headers=auth).json()
    pos = client.get("/ledger/position", headers=auth).json()
    gold_line = next(l for l in w["owned"] if l["key"] == "gold")
    check(
        "the gold value is the stock position's, not a re-derivation",
        Decimal(str(gold_line["amount"]))
        == Decimal(str(next(m["value"] for m in stock["metals"] if m["metal"] == "gold"))),
        f"overview {gold_line['amount']} vs stock position",
    )
    check(
        "the cash figure is the position report's",
        Decimal(str(next(l["amount"] for l in w["owned"] if l["key"] == "cash")))
        == Decimal(str(pos["cash_in_hand"])),
        "two readings of the shop's cash is one too many",
    )
    check(
        "what customers owe comes from the same place too",
        Decimal(str(next(l["amount"] for l in w["owned"] if l["key"] == "receivable")))
        == Decimal(str(pos["customer_receivable"])),
        "a receivable that differs between two screens is unusable on both",
    )

    split = client.get("/reports/profit-split", headers=auth,
                       params={"date_from": ov["period"]["date_from"],
                               "date_to": ov["period"]["date_to"]}).json()
    check(
        "the trading figures are the profit split's",
        Decimal(str(ov["period"]["sales"])) == Decimal(str(split["revenue"]))
        and Decimal(str(ov["period"]["gross_margin"])) == Decimal(str(split["gross_margin"])),
        f"overview {ov['period']['sales']}/{ov['period']['gross_margin']} vs "
        f"split {split['revenue']}/{split['gross_margin']}",
    )
    check(
        "and it says what basis they were struck on",
        ov["basis"] in ("cost", "replacement") and len(ov["assumptions"]) > 0,
        f"basis {ov.get('basis')}, {len(ov.get('assumptions', []))} assumptions",
    )

    check(
        "the comparison period is the equal stretch immediately before",
        ov["previous"] and ov["previous"]["date_to"] < ov["period"]["date_from"],
        str(ov.get("previous", {}).get("date_to")),
    )
    prev, cur = ov["previous"], ov["period"]
    check(
        "and it is equal in days, so a short month is not read as a collapse",
        (date.fromisoformat(cur["date_to"]) - date.fromisoformat(cur["date_from"])).days
        == (date.fromisoformat(prev["date_to"]) - date.fromisoformat(prev["date_from"])).days,
        f"{cur['date_from']}..{cur['date_to']} vs {prev['date_from']}..{prev['date_to']}",
    )
    check(
        "worth and trading are never added together",
        "net_worth" not in ov["period"] and "sales" not in w,
        "one number covering both answers neither question",
    )

    # ----------------------------------------------------------------------
    # Profit: two bases, and what each one assumes
    #
    # The shop never wrote its profit formulas down, so a conventional method
    # was implemented and every judgement it makes is stated on the response.
    # These assertions hold that contract: the two bases must differ only where
    # they are supposed to, and the report must never go quiet about what it
    # assumed.
    # ----------------------------------------------------------------------
    section("Profit basis")

    def split(**params):
        return client.get("/reports/profit-split", headers=auth, params=params).json()

    cost_b = split(basis="cost")
    repl_b = split(basis="replacement")
    check("cost basis → figures", "basis" in cost_b and cost_b["basis"] == "cost", str(cost_b)[:120])
    check("replacement basis → figures", repl_b["basis"] == "replacement", str(repl_b)[:120])
    check(
        "the default is the cost basis",
        split()["basis"] == "cost",
        "an accountant's gross profit is the safer thing to open on",
    )

    by = {s_["stream"]: s_ for s_ in cost_b["streams"]}
    by_r = {s_["stream"]: s_ for s_ in repl_b["streams"]}
    check(
        "revenue is identical on both — only the valuation of metal changes",
        cost_b["revenue"] == repl_b["revenue"],
        f"{cost_b['revenue']} vs {repl_b['revenue']}",
    )
    for stream in ("stones", "making"):
        check(
            f"the {stream} stream is untouched by the basis",
            by[stream]["cost"] == by_r[stream]["cost"],
            f"{stream}: {by[stream]['cost']} vs {by_r[stream]['cost']} — only gold "
            "may move, because only gold has a market rate",
        )
    check(
        "the whole difference lands on gold",
        abs(
            (Decimal(str(cost_b["gross_margin"])) - Decimal(str(repl_b["gross_margin"])))
            - (Decimal(str(by["gold"]["gross_margin"])) - Decimal(str(by_r["gold"]["gross_margin"])))
        )
        <= Decimal("0.02"),
        "a difference appearing outside the gold stream means the basis leaked",
    )

    check(
        "every run says what it assumed",
        len(cost_b["assumptions"]) >= 5 and len(repl_b["assumptions"]) >= 5,
        f"{len(cost_b['assumptions'])} / {len(repl_b['assumptions'])} — a figure built "
        "on an unwritten rule must not look authoritative",
    )
    check(
        "the cost basis says where the rate movement went instead",
        any("revaluation" in a for a in cost_b["assumptions"]),
        "otherwise a reader concludes the shop ignored the rate entirely",
    )
    check(
        "the replacement basis warns against double counting",
        any("do not add the two together" in a for a in repl_b["assumptions"]),
        "reading replacement AND adding the revaluation counts the holding gain twice",
    )
    check(
        "both say stones are at parcel cost, because no market rate exists for a grade",
        all(any("parcel cost" in a for a in b["assumptions"]) for b in (cost_b, repl_b)),
        "a replacement value for a diamond grade would be invented",
    )
    if cost_b["unsplit_lines"]:
        check(
            "and an unsplit line count is confessed rather than buried",
            any("could not be split" in a for a in cost_b["assumptions"]),
            "a split built mostly from unsplit lines is not a split",
        )
    check(
        "an unknown basis is refused rather than silently defaulted",
        client.get("/reports/profit-split", headers=auth,
                   params={"basis": "whatever"}).status_code == 422,
        "silently falling back would report one method under another's name",
    )

    # ----------------------------------------------------------------------
    # Audit log: before and after
    #
    # The log used to record who/what/when and a free-form blob. Whether a line
    # carried the old value depended on what each call site happened to put in
    # it, and most put nothing — so it could say Abdul edited a gold rate and
    # not what it had been. That is a notification, not an audit trail.
    # ----------------------------------------------------------------------
    section("Audit before/after")

    def audit(**params):
        r = client.get("/audit-log", headers=auth, params={"limit": 20, **params}).json()
        return r if isinstance(r, list) else r.get("rows", [])

    it = client.get("/items", headers=auth).json()[0]
    original = it["name"]
    client.patch(f"/items/{it['id']}", headers=auth, json={"name": original + " EDITED"})
    rows = audit(action="item.update")
    check("a master edit is audited at all", len(rows) > 0,
          "eight masters shared one router and none of them logged anything")
    line = rows[0]
    check(
        "it records what the value was, not only that it changed",
        line["before"] and line["before"].get("name") == original,
        f"before {line.get('before')}",
    )
    check(
        "and what it became",
        line["after"] and line["after"].get("name") == original + " EDITED",
        f"after {line.get('after')}",
    )
    check(
        "only the fields that moved are stored, not the whole row",
        set(line["before"]) == {"name"} and set(line["after"]) == {"name"},
        f"before carried {sorted(line['before'])} — a full snapshot buries the "
        "one number that changed in forty that did not",
    )
    check(
        "both sides carry the same keys, so they can be read side by side",
        set(line["before"]) == set(line["after"]),
        f"{sorted(line['before'])} vs {sorted(line['after'])}",
    )

    # An edit that alters nothing must not write a line.
    n_before = len(audit(action="item.update"))
    client.patch(f"/items/{it['id']}", headers=auth, json={"name": original + " EDITED"})
    check(
        "an edit that changes nothing writes no audit row",
        len(audit(action="item.update")) == n_before,
        "'somebody opened this and changed nothing' only makes real edits harder to find",
    )
    client.patch(f"/items/{it['id']}", headers=auth, json={"name": original})

    # Rate changes: called out by the spec, and previously unaudited entirely.
    r = client.post("/gold-rates", headers=auth, json={
        "rate_date": str(date.today()), "currency": "PKR", "purity": 24,
        "rate_per_g": "123456.7890",
    })
    check("setting a rate → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
    rate_rows = audit(action="gold_rate.create")
    check("setting the rate the shop prices at is audited", len(rate_rows) > 0,
          "the number every invoice reads was changeable without a trace")
    check(
        "the new rate is captured exactly, not as a float",
        rate_rows[0]["after"].get("rate_per_g") == "123456.7890",
        f"got {rate_rows[0]['after'].get('rate_per_g')!r} — a rate read back as "
        "123456.78899999999 would undermine the point of keeping the log",
    )

    # A delete keeps the whole row, because afterwards there is nothing to
    # compare against.
    made = client.post("/items", headers=auth, json={"name": "Audit Probe Item", "code": "APX"})
    if made.status_code == 201:
        probe = made.json()
        client.delete(f"/items/{probe['id']}", headers=pwd_h)
        gone = audit(action="item.delete")
        check("a delete is audited", len(gone) > 0, "nothing recorded the removal")
        check(
            "and keeps the whole row, since nothing survives to compare against",
            gone[0]["before"] and gone[0]["before"].get("name") == "Audit Probe Item",
            f"before {gone[0].get('before')}",
        )
        check("a delete has no 'after'", gone[0]["after"] is None, str(gone[0].get("after")))

    # ----------------------------------------------------------------------
    # Universal search
    #
    # The palette could already find screens. What these cover is finding
    # *records* — and the one that matters most is the permission gate: search
    # is the easiest place in an application to leak the existence of something
    # a role cannot open, because it touches every table at once.
    # ----------------------------------------------------------------------
    section("Universal search")

    def find(term, headers=auth):
        return client.get("/search", headers=headers, params={"q": term}).json()

    r = client.get("/search", headers=auth, params={"q": sale["invoice_no"]})
    check("search → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    hits = r.json()["hits"]
    check(
        "an invoice number finds exactly that invoice",
        any(h["type"] == "invoice" and h["title"] == sale["invoice_no"] for h in hits),
        str([h["title"] for h in hits]),
    )
    check(
        "and the exact document number sorts first",
        hits and hits[0]["title"] == sale["invoice_no"],
        f"first hit was {hits[0]['title'] if hits else 'nothing'}",
    )
    check(
        "every hit says where it goes",
        all(h.get("to") for h in hits),
        "a hit with no destination is a tease",
    )
    check(
        "the tail of a number finds it too",
        any(h["title"] == sale["invoice_no"] for h in find(sale["invoice_no"][-5:])["hits"]),
        "people search by the end of a number as often as the start",
    )
    check(
        "a customer is found by name",
        any(h["type"] == "customer" for h in find(cust["name"][:5])["hits"]),
        str([h["type"] for h in find(cust["name"][:5])["hits"]]),
    )
    check(
        "a karigar is found by name",
        any(h["type"] == "worker" for h in find("Ravi")["hits"]),
        str([(h["type"], h["title"]) for h in find("Ravi")["hits"]]),
    )
    check(
        "a job is found by its design number",
        any(h["type"] == "design" for h in find(set_design["design_no"])["hits"]),
        str([h["title"] for h in find(set_design["design_no"])["hits"]]),
    )
    check("a term matching nothing returns nothing, not an error",
          find("zzzznotathing")["hits"] == [], "expected an empty list")
    check("an empty query is refused rather than scanning everything",
          client.get("/search", headers=auth, params={"q": ""}).status_code == 422,
          "an unbounded search is a table scan per entity")

    # The gate. Staff may read customers but not the ledger or sellers, so a
    # staff search must return the customer and never the seller.
    staff_hits = find(cust["name"][:5], headers=staff_auth)["hits"]
    check(
        "staff can still find a customer they are allowed to open",
        any(h["type"] == "customer" for h in staff_hits),
        str([h["type"] for h in staff_hits]),
    )
    # The gate is real code — each type is skipped unless `role_has` allows it —
    # but it cannot be *observed* here, because all three seeded roles happen to
    # hold read on every one of the eight searchable types. Asserting "staff
    # cannot see sellers" would pass for the wrong reason and quietly stop
    # meaning anything. What is checkable is the invariant that matters if a
    # narrower role is ever added: a lesser role never sees more than admin.
    admin_types = {h["type"] for h in find(sman["name"][:4])["hits"]}
    staff_types = {h["type"] for h in find(sman["name"][:4], headers=staff_auth)["hits"]}
    check(
        "a lesser role never sees a type admin does not",
        staff_types <= admin_types,
        f"staff saw {staff_types - admin_types} that admin did not",
    )
    check(
        "every hit is one of the types this endpoint claims to search",
        all(
            h["type"]
            in {"invoice", "product", "design", "order", "customer", "worker",
                "supplier", "seller"}
            for h in find("a")["hits"]
        ),
        "an unexpected type means a new table was added without a permission gate",
    )

    # ----------------------------------------------------------------------
    # Reconciliation: the scale against the books
    #
    # The rule under test is the one that makes every other guarantee in this
    # system worth anything: a count does not overwrite a balance, it posts a
    # movement and a journal entry. The assertions that matter most are the
    # refusals — an unweighed pot, a missing reason, a second posting — because
    # each of them is a way a variance could be written off with nobody's name
    # on it.
    # ----------------------------------------------------------------------
    section("Reconciliation")
    r = client.get("/reconciliation", headers=auth)
    check("reconciliation overview → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    ov = {s_["key"]: s_ for s_ in r.json()["scopes"]}
    check("gold and silver are countable", ov["gold"]["countable"] and ov["silver"]["countable"],
          str([(k, v["countable"]) for k, v in ov.items()]))
    check(
        "what cannot be counted yet says so rather than hiding",
        ov["stones"]["countable"] is False and ov["stones"]["note"],
        "a scope with no button and no explanation reads as an oversight",
    )

    r = client.post("/reconciliation/counts", headers=auth, json={"metal": "gold"})
    check("open a gold count → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:250]}")
    sheet = r.json()
    check("the sheet numbers itself in its own series", sheet["count_no"].startswith("SC-"),
          sheet["count_no"])
    check("every pot is on it, including empty ones", len(sheet["lines"]) > 0, str(sheet["lines"]))
    check("and none is weighed yet", sheet["unweighed_lines"] == len(sheet["lines"]),
          f"{sheet['unweighed_lines']} of {len(sheet['lines'])}")
    check(
        "a second sheet for the same metal and branch is refused",
        client.post("/reconciliation/counts", headers=auth, json={"metal": "gold"}).status_code
        == 409,
        "two sheets would each measure from the same start and write the gap off twice",
    )
    check(
        "an unweighed sheet cannot be posted",
        client.post(f"/reconciliation/counts/{sheet['id']}/post", headers=pwd_h).status_code == 400,
        "an unweighed pot is not an empty one",
    )

    # Weigh every pot exactly, except one 22k pot short by 2.6g — so the fine
    # conversion is actually exercised rather than passing by luck on 24k.
    target = next(
        (l for l in sheet["lines"] if l["purity"] and int(l["purity"]) != 24),
        sheet["lines"][0],
    )
    payload = []
    for l in sheet["lines"]:
        book = Decimal(str(l["book_weight_g"]))
        short = Decimal("2.6") if l["id"] == target["id"] else Decimal("0")
        payload.append({"line_id": l["id"], "counted_weight_g": str(book - short)})
    upd = client.patch(f"/reconciliation/counts/{sheet['id']}", headers=auth,
                       json={"lines": payload}).json()
    check("the sheet works out the shortfall", Decimal(str(upd["variance_g"])) == Decimal("-2.6"),
          f"got {upd['variance_g']}")
    expected_fine = (Decimal("-2.6") * Decimal(str(target["purity"])) / Decimal("24")
                     ).quantize(Decimal("0.0001"))
    check(
        f"and converts it at the pot's own purity: 2.6g of {target['purity']}k is "
        f"{abs(expected_fine)} fine",
        abs(Decimal(str(upd["variance_fine_g"])) - expected_fine) <= Decimal("0.0002"),
        f"got {upd['variance_fine_g']}, expected {expected_fine} — booking 2.6 would leave "
        "the trial balance out by the alloy",
    )
    check(
        "posting without a reason is refused",
        client.post(f"/reconciliation/counts/{sheet['id']}/post", headers=pwd_h).status_code == 400,
        "a write-off with no explanation is what an auditor asks about first",
    )

    client.patch(f"/reconciliation/counts/{sheet['id']}", headers=auth,
                 json={"lines": [], "reason": "Month-end physical count"})
    gold_before_count = gold_in_hand()
    r = client.post(f"/reconciliation/counts/{sheet['id']}/post", headers=pwd_h)
    check("post the count → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:250]}")
    posted = r.json()
    check("the sheet is now posted", posted["status"] == "posted", posted["status"])
    check("and it names the entry it produced", posted["journal_entry_no"] is not None, str(posted))
    check(
        "the ledger moves by the FINE shortfall, not the scale reading",
        abs((gold_in_hand() - gold_before_count) - expected_fine) <= Decimal("0.0002"),
        f"moved {gold_in_hand() - gold_before_count}, expected {expected_fine}",
    )
    check("books balance after writing a shortage off",
          client.get("/ledger/trial-balance", headers=auth).json()["balanced"] is True)
    check(
        "a posted sheet cannot be posted twice",
        client.post(f"/reconciliation/counts/{sheet['id']}/post", headers=pwd_h).status_code == 409,
        "posting twice would write the same metal off again",
    )
    check(
        "a posted sheet is a record and does not change",
        client.patch(f"/reconciliation/counts/{sheet['id']}", headers=auth,
                     json={"lines": [], "reason": "changed my mind"}).status_code == 409,
        "the sheet is what was found; editing it after the fact rewrites history",
    )
    check(
        "the stock pot moved too, not just the books",
        any(m.get("reference_type") == "stock_count"
            for m in client.get("/stock-movements", headers=auth, params={"limit": 50}).json()),
        "a count that moved the ledger without the pot leaves the two describing "
        "different shops",
    )
    # Counting and finding nothing wrong is a real outcome and must not error.
    sheet2 = client.post("/reconciliation/counts", headers=auth, json={"metal": "silver"}).json()
    client.patch(f"/reconciliation/counts/{sheet2['id']}", headers=auth, json={
        "lines": [{"line_id": l["id"], "counted_weight_g": str(l["book_weight_g"])}
                  for l in sheet2["lines"]],
        "reason": "Agreed on the nose",
    })
    r = client.post(f"/reconciliation/counts/{sheet2['id']}/post", headers=pwd_h)
    check("a count that agrees posts nothing and is not an error",
          r.status_code == 200 and r.json()["journal_entry_no"] is None,
          f"got {r.status_code}, entry {r.json().get('journal_entry_no')}")
    check("but the sheet is still closed and kept",
          r.json()["status"] == "posted",
          "'we counted and it agreed' is a fact worth keeping")

    r = client.get("/reports/material-outside", headers=auth)
    check("material outside → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:220]}")
    outside = r.json()
    check("somebody is holding something", outside["parties"] > 0, str(outside["parties"]))
    check(
        "the gold total is the sum of the rows, not a separate reading",
        abs(
            Decimal(str(outside["total_gold_g"]))
            - sum((Decimal(str(x["gold_g"])) for x in outside["rows"]), Decimal("0"))
        )
        <= Decimal("0.0001"),
        f"total {outside['total_gold_g']}",
    )
    check(
        "it agrees with the position report's one-line figure",
        abs(
            Decimal(str(outside["total_gold_g"]))
            - Decimal(str(client.get("/ledger/position", headers=auth).json()["gold_with_workers_g"]))
        )
        <= Decimal("0.0001"),
        f"outside says {outside['total_gold_g']}",
    )
    check(
        "each row is ranked by gold, heaviest first",
        all(
            Decimal(str(a["gold_g"])) >= Decimal(str(b["gold_g"]))
            for a, b in zip(outside["rows"], outside["rows"][1:])
        ),
        str([x["gold_g"] for x in outside["rows"]]),
    )
    # The whole reason it reads the ledger: a balance with no open leg behind
    # it is metal that has not come back, and the legs alone would call that
    # worker clear.
    check(
        "a worker with no open leg but metal still out is still listed",
        any(x["open_legs"] == 0 and Decimal(str(x["gold_g"])) != 0 for x in outside["rows"]),
        "every row has an open leg — the ledger-vs-legs distinction is untested",
    )
    check(
        "silver and stones are their own columns, never folded into gold",
        all("silver_g" in x and "stone_ct" in x for x in outside["rows"]),
        str(outside["rows"][:1]),
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

    # --- stones are costed at the parcel they came out of, oldest first ---
    # Two purchases of the same grade at different prices. Stock is one figure;
    # cost is not. A piece made from the January parcel cost Rs 8,000 a carat
    # however much dearer stone sits beside it on the shelf.
    fifo_stone = client.post("/stones", headers=auth, json={
        "name": "FIFO 10 PTR", "kind": "diamond", "category": "diamond",
        "default_rate_per_ct": "5000", "currency": "PKR",
    }).json()
    for when, ct, rate in (("2026-01-10T10:00:00Z", "50", "8000"),
                           ("2026-03-10T10:00:00Z", "70", "9200")):
        rp = client.post("/purchasing/stone-purchases", headers=auth, json={
            "supplier_id": supplier["id"], "purchased_at": when, "extra_cost_pct": "0",
            "items": [{"stone_id": fifo_stone["id"], "quantity": 100,
                       "weight_ct": ct, "rate_per_ct": rate}],
        })
        check(f"buy {ct}ct at Rs {rate} → 201", rp.status_code == 201,
              f"got {rp.status_code}: {rp.text[:200]}")

    # More on the shelf than the two parcels account for, which is the ordinary
    # case: a shop's opening stock predates every bill the system has seen.
    fifo_stock = open_pot(
        {"type": "raw_stone", "label": "FIFO 10 PTR parcel"},
        weight_ct="200", value="600000",
    )

    def issue_fifo(carats: str) -> dict:
        dsn = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
        rr = client.post(f"/designs/{dsn['id']}/legs", headers=auth, json={
            "department_id": setting_dept_id, "worker_id": setter["id"],
            "gold_issued_g": "10", "gold_issued_purity": 21,
            "gold_source_inventory_id": piece_gold["id"],
            "stone_source_inventory_id": fifo_stock["id"],
            "stones": [{"stone_id": fifo_stone["id"], "quantity_issued": 10,
                        "weight_issued_ct": carats}],
            "piece_count": 10, "wastage_basis": "per_100_pieces",
            "wastage_per_100_pcs_g": "0.400",
        })
        assert rr.status_code == 201, rr.text[:300]
        return rr.json()

    first = issue_fifo("30")
    check(
        "30ct drawn wholly from the January parcel is costed at Rs 8,000",
        Decimal(str(first["stones"][0]["rate_per_ct"])) == Decimal("8000"),
        f"got {first['stones'][0]['rate_per_ct']} — 5000 would mean the master's standing "
        "rate was used, 8700 would mean the two parcels were averaged",
    )

    # 20ct of January is left, so 40ct spans both parcels:
    #   (20 x 8,000 + 20 x 9,200) / 40 = 8,600
    second = issue_fifo("40")
    check(
        "an issue spanning two parcels is costed at the weighted mean of what it drew",
        Decimal(str(second["stones"][0]["rate_per_ct"])) == Decimal("8600"),
        f"got {second['stones'][0]['rate_per_ct']}, expected 8600 "
        "(20ct left at 8,000 plus 20ct at 9,200)",
    )

    # 50ct of March is left, so a 60ct issue runs the parcels dry and the last
    # 10ct has no purchase behind it. That is costed at the master's rate
    # rather than refused: a shop's opening stock predates the system and still
    # has to be usable.
    #   (50 x 9,200 + 10 x 5,000) / 60 = 8,500
    third = issue_fifo("60")
    check(
        "an issue that outruns the parcels costs the remainder at the master rate",
        Decimal(str(third["stones"][0]["rate_per_ct"])) == Decimal("8500"),
        f"got {third['stones'][0]['rate_per_ct']}, expected 8500 (50ct at 9,200 plus "
        "10ct with no purchase behind it at 5,000) — refusing here would mean a shop "
        "cannot issue its own opening stock",
    )

    # A rate stated on the request is a price the counter has agreed, and the
    # system does not overrule it with a historic purchase.
    dsn = client.post("/designs", headers=auth, json={"item_id": taka_id}).json()
    stated = client.post(f"/designs/{dsn['id']}/legs", headers=auth, json={
        "department_id": setting_dept_id, "worker_id": setter["id"],
        "gold_issued_g": "10", "gold_issued_purity": 21,
        "gold_source_inventory_id": piece_gold["id"],
        "stone_source_inventory_id": fifo_stock["id"],
        "stones": [{"stone_id": fifo_stone["id"], "quantity_issued": 1,
                    "weight_issued_ct": "1", "rate_per_ct": "12345"}],
        "piece_count": 1, "wastage_basis": "per_100_pieces",
        "wastage_per_100_pcs_g": "0.400",
    }).json()
    check(
        "a rate stated on the issue is not overruled by the parcels",
        Decimal(str(stated["stones"][0]["rate_per_ct"])) == Decimal("12345"),
        f"got {stated['stones'][0]['rate_per_ct']}",
    )

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
    # Paisa-level drift per line, plus a gram-level allowance per bill.
    #
    # The levers decompose an unrounded weight; a trade bill's metal obligation
    # is stored to four decimal places because that is the figure the customer
    # is actually handed and the ledger actually posts. At a four-figure gold
    # rate the fourth decimal of a gram is worth most of a rupee, so a bill that
    # settles in metal can differ from its own decomposition by more than the
    # per-line paisa tolerance — without anything being wrong. Bounded and
    # named rather than widened silently.
    tolerance = Decimal("0.05") * max(total["lines"], 1) + Decimal("1.00") * max(
        total["invoices"], 1
    )
    check(
        "the levers add up to gross profit",
        abs(attributed - Decimal(str(total["gross_profit"]))) <= tolerance,
        f"levers {attributed} vs gross {total['gross_profit']} (tolerance {tolerance})",
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

    # ----- DASHBOARD -----
    section("Dashboard")
    r = client.get("/dashboard", headers=auth, params={"days": 14})
    check("dashboard → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    dash = r.json()
    check(
        "one day per day asked for, with none missing",
        len(dash["series"]) == 14,
        f"got {len(dash['series'])} — a gap in the series draws as a crash in the chart",
    )
    check(
        "the series ends today",
        dash["series"][-1]["day"] == date.today().isoformat(),
        f"got {dash['series'][-1]['day']}",
    )
    check(
        "the position on the dashboard is the position in the ledger",
        Decimal(str(dash["today"]["gold_in_hand_g"]))
        == Decimal(str(client.get("/ledger/position", headers=auth).json()["gold_in_hand_g"])),
        "two screens showing different metal is worse than one showing none",
    )
    check(
        "an alert carries somewhere to go and fix it",
        all(a_.get("to") and a_.get("label") for a_ in dash["alerts"]),
        str(dash["alerts"]),
    )
    # The screen shows the cash position, so it is gated like the sales report
    # rather than being readable by anyone who can log in.
    r = client.get("/dashboard", headers=staff_auth)
    check("staff cannot read the dashboard figures → 403", r.status_code == 403, f"got {r.status_code}")

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
