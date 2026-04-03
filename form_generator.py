from sheets import read_sheet

def generate_form_content():
    print("Reading tracker...")
    rows = read_sheet("LDP Tracker")
    
    tbd = [r for r in rows 
           if r.get('Batch','').strip() == 'TBD']
    
    hrbps = sorted(set(
        r.get('HRBP Name','').strip() 
        for r in tbd
    ))
    
    employees = sorted(
        r.get('Employee Name','').strip() 
        for r in tbd
    )
    
    print("\n" + "="*60)
    print("GOOGLE FORM SETUP GUIDE")
    print("="*60)
    
    print("\n FORM TITLE:")
    print("LDP Batch 04 Nominations — 28-29 April 2026")
    
    print("\n FORM DESCRIPTION:")
    print("""Please select the employees you wish to nominate 
for LDP Batch 04 (28-29 April 2026). 
Nomination deadline: 7 April 2026.
Only select employees from your business unit.""")
    
    print("\n QUESTION 1 — Dropdown (Required)")
    print("Label: Your Name (HRBP)")
    print("Options:")
    for h in hrbps:
        print(f"  • {h}")
    
    print(f"\n QUESTION 2 — Checkboxes (Required)")
    print("Label: Select employees to nominate")
    print(f"Options ({len(employees)} total):")
    for e in employees:
        print(f"  • {e}")
    
    print("\n QUESTION 3 — Paragraph (Optional)")
    print("Label: Comments or special considerations")
    print("(e.g. employee on leave, defer to next batch)")
    
    print("\n QUESTION 4 — Multiple choice (Required)")
    print("Label: I confirm these nominations are accurate")
    print("Option: Yes, I confirm")
    
    print("\n" + "="*60)
    print(f"Total: {len(hrbps)} HRBPs | {len(employees)} employees")
    print("="*60)

generate_form_content()
