from process_opta_data import OptaProcessor
import pandas as pd

processor = OptaProcessor()
file_path = 'd:/Montage video football/ClipMaker 1.1 by B4L1 - WIndows/Exemple/eventing-Spain_2025_2026_Copa_del_Rey_J_Albacete_vs_Barcelona-2026-02-03.xlsx'
events = processor.process_file(file_path)

cross_events = [e for e in events if e.get('adv_CROSS')]
print(f"Total events: {len(events)}")
print(f"Total cross events found: {len(cross_events)}")

if len(cross_events) > 0:
    print("Example cross event:")
    print({k: cross_events[0][k] for k in ['minute', 'second', 'type', 'adv_CROSS']})
    print("Qualifiers for this event:")
    print(cross_events[0].get('qualifiers'))
else:
    # Print a few passes to see their qualifiers
    passes = [e for e in events if e['type'] == 'Pass'][:5]
    print("\nFirst 5 passes and their qualifiers:")
    for p in passes:
        print(f"Time: {p['minute']}:{p['second']} - Qualifiers: {p.get('qualifiers')}")
