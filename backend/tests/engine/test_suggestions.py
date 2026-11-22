from app.scheduling import generate, suggest, validate
from app.scheduling.types import EntryStatus, Role, RosterDuty, RosterEntry

from .builder import D, GEN, PB


def test_suggests_trained_backup_for_gap_created_by_new_leave():
    pb = PB()
    owner, buddy = pb.employee("Owner", pod=1), pb.employee("Buddy", pod=1)
    cs = pb.bp("Ember", "CS")
    s = pb.slot(cs, GEN, 1)
    pb.assign(owner, cs)
    own = pb.bp("Kito", "CS")
    pb.slot(own, GEN, 1)
    pb.assign(buddy, own, load=70)
    b_asg = pb.assign(buddy, cs, Role.BACKUP, load=50)
    roster = generate(pb.build()).roster

    # Pick a day the owner works and the buddy also works, then give the owner leave.
    em = roster.entry_map()
    day = next(D(i) for i in range(1, 32)
               if em[(owner, D(i))].status == EntryStatus.WORK and em[(buddy, D(i))].status == EntryStatus.WORK)
    pb.leave(owner, day, day)
    prob = pb.build()
    roster.entries = [RosterEntry(owner, day, EntryStatus.LEAVE) if (x.employee_id, x.date) == (owner, day)
                      else x for x in roster.entries]
    roster.duties = [x for x in roster.duties if not (x.employee_id == owner and x.date == day)]
    rep = validate(prob, roster)
    assert any(g.slot_id == s and g.date == day for g in rep.gaps)

    sugg = suggest(prob, roster, s, day)
    assert sugg and sugg[0].employee_id == buddy and sugg[0].action == "ADD_DUTY"
    assert sugg[0].assignment_id == b_asg and "same pod" in sugg[0].reasons

    # Applying the suggestion closes the gap and keeps the roster rule-valid.
    roster.duties.append(RosterDuty(buddy, day, s, cs, GEN, b_asg, Role.BACKUP, ))
    rep2 = validate(prob, roster)
    assert not any(g.slot_id == s and g.date == day for g in rep2.gaps)
    assert rep2.hard_rule_violations == 0


def test_absent_people_are_never_suggested():
    pb = PB()
    owner, buddy = pb.employee("Owner"), pb.employee("Buddy")
    cs = pb.bp("Ember", "CS")
    s = pb.slot(cs, GEN, 1)
    pb.assign(owner, cs)
    pb.assign(buddy, cs, Role.BACKUP, load=50)
    pb.leave(owner, D(10), D(10))
    pb.leave(buddy, D(10), D(10))
    prob = pb.build()
    roster = generate(prob).roster
    assert suggest(prob, roster, s, D(10)) == []
