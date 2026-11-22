import pytest

from app.scheduling.types import OffPolicy, Role

from .builder import D, EVE, GEN, MON_SAT, MOR, NGT, PB


@pytest.fixture
def rich_problem():
    """A compact multi-brand scenario mixing every rule type."""
    pb = PB()
    pb.holiday(D(25), "Christmas")
    lead = pb.employee("Lead Lata", pod=1)
    e = {n: pb.employee(n, pod=1 + i % 2) for i, n in enumerate(
        ["Asha", "Bilal", "Chitra", "Dev", "Esha", "Farid", "Gita", "Hari"])}
    night = pb.employee("Nina Night", pod=2, policy=OffPolicy(min_rest_hours=12))

    # Single-resource 365-day brand with a backup.
    lumo = [pb.bp("Lumo", p, holidays=True) for p in ("CS", "NDR")]
    for bp, load in zip(lumo, (70, 30)):
        pb.slot(bp, GEN, 1)
        pb.assign(e["Asha"], bp, load=load)
        pb.assign(lead, bp, Role.BACKUP, load=load // 2)
    # Single-resource Mon-Sat brand, holidays off.
    kito = pb.bp("Kito", "CS", MON_SAT)
    pb.slot(kito, GEN, 1)
    pb.assign(e["Bilal"], kito, load=60)
    pb.assign(lead, kito, Role.BACKUP, load=30)
    # Lead owns a small brand.
    zest = pb.bp("Zest", "CS", MON_SAT)
    pb.slot(zest, GEN, 1)
    pb.assign(lead, zest, load=40)
    # Multi-resource brand: shared CS with weekend minimum 2, separate ACC.
    urb_cs, urb_acc = pb.bp("Urban", "CS"), pb.bp("Urban", "ACC", MON_SAT)
    s = pb.slot(urb_cs, GEN, 1)
    pb.override(s, 2, dow=5)
    pb.slot(urb_acc, GEN, 1)
    for n in ("Chitra", "Dev", "Esha"):
        pb.assign(e[n], urb_cs, load=60)
    pb.assign(e["Esha"], urb_acc, load=40)
    pb.assign(e["Dev"], urb_acc, Role.BACKUP, load=30)
    # Shift-specific coverage: MOR + EVE + NGT on one process.
    glow = pb.bp("Glow", "CS")
    pb.slot(glow, MOR, 1)
    pb.slot(glow, EVE, 1)
    pb.slot(glow, NGT, 1)
    pb.assign(e["Farid"], glow, load=100)
    pb.assign(e["Gita"], glow, load=100)
    pb.assign(e["Hari"], glow, load=100, shift=EVE)
    pb.assign(night, glow, load=100, shift=NGT)
    pb.leave(e["Gita"], D(21), D(23))
    return pb.build()
