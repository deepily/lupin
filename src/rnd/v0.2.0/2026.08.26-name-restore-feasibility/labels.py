# Pinned to the 2026-08-26 corpus snapshot via sample.json / role_sample.json - see README.md.
# Clayton's hand labels for the 60 stratified cases (§3 of the doc).
# Every value here was assigned by reading the case, not computed.
LABELS = {
 0:("IMPOSSIBLE","whole claim about Arnold gone; delivered is a different topic"),
 1:("ARTIFACT-ident","only mention was inside 'cc-author-maria-3'"),
 2:("IMPOSSIBLE","'the only outstanding review is Rio's' gone; delivered says all closed"),
 3:("IMPOSSIBLE","off-peak/Rick sentence gone entirely"),
 4:("IMPOSSIBLE","'Mr Radio handed me the ten reds' gone; delivered mangles voice"),
 5:("IMPOSSIBLE","'That was my error, not Sam's' gone; sha restored, exculpation not"),
 6:("NEEDS-REWRITE","'the checker' survives; 'Sam's' fits grammatically but carries a different claim than the one dropped"),
 7:("IMPOSSIBLE","'Rio's fix is uncommitted' gone; surviving reference is to the tree, not to Rio"),
 8:("IMPOSSIBLE","'one word from you or Rick' gone; delivered is generic third person"),
 9:("IMPOSSIBLE","'Arnold's diff isn't landed' gone; delivered is about contract pinning"),
10:("IMPOSSIBLE","both Rick sentences gone"),
11:("ARTIFACT-ident","only mention was inside task_query(owner_persona=john)"),
12:("IMPOSSIBLE","'Mr. Radio was killed in a worktree' gone"),
13:("IMPOSSIBLE","'Rick picked the field that cannot be empty' gone"),
14:("ARTIFACT-sig","'Tiberius, reviewer 1.' — sender's own signature"),
15:("IMPOSSIBLE","both Rick sentences gone incl. the contrast that made the point"),
16:("IMPOSSIBLE","'Rick's decision should carry that sentence' gone"),
17:("IMPOSSIBLE","'I am telling Rick now' gone"),
18:("ARTIFACT-sig","'Rachel - BLOCKER-SHAPED FINDING' — sender's own signature line"),
19:("ARTIFACT-sig","'Maria - both corrections taken' — sender's own signature line"),
20:("ARTIFACT-sig","'- Rachel' trailing signature"),
21:("IMPOSSIBLE","'That's Rick's to resolve' gone"),
22:("IMPOSSIBLE","'acking Rick's broadcast ee1a49ce' gone; sha survives in pointer block, prose does not"),
23:("IMPOSSIBLE","'before John re-runs' gone"),
24:("IMPOSSIBLE","'adce3547 blocked on rick' gone; row id survives, blocker does not"),
25:("NEEDS-REWRITE","exclusion survives, 'Rick ruled that split' must be re-added as a clause"),
26:("NEEDS-REWRITE","the 7-to-10 number survives; no noun phrase for 'Maria's' to attach to"),
27:("IMPOSSIBLE","'folding it into Rick's 22:00 rotation' gone"),
28:("IMPOSSIBLE","both Rick sentences gone"),
29:("IMPOSSIBLE","'open decision for Rick' gone"),
30:("IMPOSSIBLE","'Clayton pushed back on my ratio' gone"),
31:("NEEDS-REWRITE","the dependency on Krishna's step 2 is gone, not just his name"),
32:("NEEDS-REWRITE","the ruling survives, the ruler does not; restoring means authoring a clause"),
33:("IMPOSSIBLE","'Rick's four ratified decisions' gone"),
34:("IMPOSSIBLE","both Rick sentences gone"),
35:("CLEAN","delivered 'If she ran at HEAD... her exact sha' — unbound pronoun, Maria drops in"),
36:("NEEDS-REWRITE","condenser SUBSTITUTED 'from a different command' for 'from Rio's pre-respin session'"),
37:("IMPOSSIBLE","'before Clayton's fix exists' gone"),
38:("IMPOSSIBLE","both Rick sentences gone"),
39:("IMPOSSIBLE","'putting the scheduling question to Rick' gone"),
40:("IMPOSSIBLE","'break-test alongside arnold' gone"),
41:("IMPOSSIBLE","'Rio signed off the seam pin' gone; sha survives, signer does not"),
42:("ARTIFACT-sig","'- Rachel' trailing signature"),
43:("NEEDS-REWRITE","'fixed by Sam' survives; Rio-as-recorder needs a re-added clause"),
44:("IMPOSSIBLE","'Clayton clear to bounce :8000' gone"),
45:("IMPOSSIBLE","'I'll have Rio break-test' gone"),
46:("IMPOSSIBLE","'tell John the shape changed' gone"),
47:("ARTIFACT-sig","'- Tiffany' trailing signature"),
48:("ARTIFACT-sig","'- Tiffany' trailing signature"),
49:("IMPOSSIBLE","'the reviewer' looks like a slot but identity is unverifiable from the message - see doc 5c"),
50:("IMPOSSIBLE","'Rick un-parked it on my ask' gone; row id survives"),
51:("NEEDS-REWRITE","the instruction survives, the authority behind it does not"),
52:("IMPOSSIBLE","'while Clayton's unit pass runs' gone"),
53:("CLEAN","delivered 'ready to apply on his word' — unbound 'his', Rick drops in"),
54:("IMPOSSIBLE","'the push to origin is still Rick's alone' gone; delivered has no push at all"),
55:("IMPOSSIBLE","'Rick's epic-accordion build' gone"),
56:("ARTIFACT-sig","'Mr Radio - re-spun, same seat' — sender's own signature line"),
57:("IMPOSSIBLE","'Rick called end-of-session rituals' gone"),
58:("NEEDS-REWRITE","'a commitment to another task' replaced 'Rick's KISS Protocol explainer'"),
59:("IMPOSSIBLE","'That call is now in front of Rick' gone"),
}

# The 18-case complete census (doc section 5). Same rule: read, not computed.
CENSUS = {
 "U00":("WRONG-PERSON","'his amend' is the implementer, not Maria"),
 "U01":("CLEAN","'before his guard exists' -> Arnold's guard"),
 "U02":("WRONG-PERSON","'take his board' - dropped name is the ADDRESSEE; the pronouns are a third party"),
 "U03":("CLEAN","'if he stalls' -> if Rio stalls"),
 "U04":("CLEAN","'He has the negative arm covered' -> Pocholo"),
 "U05":("UNDECIDED","'he paid a price he doesn't owe' - could not resolve from the message; left unclassified"),
 "U06":("CLEAN","'read what she WROTE' -> Maria"),
 "U07":("WRONG-PERSON","'like author grading his own work' - generic 'his'; restoring Rick is nonsense and false"),
 "U08":("WRONG-PERSON","'from HER seat' - feminine; dropped name is Rick"),
 "U09":("CLEAN","'when he is back' -> when Rick is back"),
 "U10":("CLEAN","'should be committed by her' -> Maria"),
 "U11":("CLEAN","'that you have his word' -> Rick's word"),
 "U12":("CLEAN","'her claims / her receipt / Her proof' -> Maya"),
 "U13":("WRONG-PERSON","'his probe run' - Maya's dropped sentence was about a rescued check, not a probe"),
 "U14":("CLEAN","'Get her eight verbatim strings' -> Rachel's"),
 "U15":("CLEAN","'does it wait on her?' -> on Tiffany"),
 "U16":("CLEAN","'If she ran at HEAD... her exact sha' -> Maria"),
 "U17":("CLEAN","'his ruling' -> Rick's ruling"),
}


# The 20 role-noun cases read for section 5d (Krishna's specimen shape). Read, not computed.
# Question asked of each: does the role noun in the delivered text stand for the DROPPED person?
ROLE_20 = {
 "R00":("SENDER","'The agent acknowledges their initial alarm was incorrect' = Maria (sender); dropped = Cheech"),
 "R01":("SENDER","'The author will defend and revise their work' = Maria; dropped = Rick"),
 "R02":("SENDER","'The agent is asking if they should archive' = Krishna; dropped = John"),
 "R03":("SENDER","'The author will verify file names' = Mr Radio; dropped = Clayton"),
 "R04":("NO-SLOT","role noun present but none stands for the dropped Rick"),
 "R05":("NO-SLOT","role noun present but none stands for the dropped Rick"),
 "R06":("SENDER","'The sender has provided the necessary information' = Cheech; dropped = Rick"),
 "R07":("NO-SLOT","role noun present but none stands for the dropped Rick"),
 "R08":("SENDER","'The agent reported a discrepancy... their own guess' = Tiffany; dropped = Rick"),
 "R09":("SENDER","'The sender has capacity to take on the task' = Maria; dropped = Rick"),
 "R10":("NO-SLOT","role noun present but none stands for the dropped Rick"),
 "R11":("SENDER","three 'The sender's, all Maria; dropped = Rick - the doc's headline example"),
 "R12":("SENDER","'The agent reassigned 30483697 to themselves' = Mr Radio; dropped = Rick"),
 "R13":("NO-SLOT","role noun present but none stands for the dropped Sam"),
 "R14":("NO-SLOT","role noun present but none stands for the dropped Rick"),
 "R15":("AMBIGUOUS","'The author has identified issues with _has_question' - could be Krishna (dropped, authored bcffa558) or pocholo (sender); undecidable from the message"),
 "R16":("RECIPIENT","'not the recipient's responsibility' = Rachel (addressee); dropped = Maya"),
 "R17":("NO-SLOT","role noun present but none stands for the dropped Rio"),
 "R18":("SENDER","'The sender has delegated the task to the recipient' = Tiberius; dropped = Rick"),
 "R19":("NO-SLOT","role noun present but none stands for the dropped Rachel"),
}
# Tally: 0 of 20 role nouns stand for the DROPPED person.
#        10 stand for the sender, 1 for the recipient, 8 have no slot for the dropped name,
#        1 is undecidable. Restoring the dropped name into the role noun is wrong in all 20.

if __name__ == "__main__":
    import json, collections
    s = json.load( open( "sample.json" ) )
    assert len( LABELS ) == 60 == len( s )
    c = collections.Counter( v[0] for v in LABELS.values() )
    for k, v in c.most_common(): print( "%-16s %d" % ( k, v ) )
    print( "-" * 40 )
    cc = collections.Counter( v[0] for v in CENSUS.values() )
    print( "-" * 40 )
    print( "18-case census:", dict( cc ) )
    print( "20 role-noun cases:", dict( collections.Counter( v[0] for v in ROLE_20.values() ) ) )
    print( "-" * 40 )
    for i in range( 60 ):
        x = s[i]; lab, why = LABELS[i]
        print( "%02d | %-16s | %-9s | %s -> %s | %s" % ( i, lab, x["_lost"][0], x["from"], x["to"], why ) )
