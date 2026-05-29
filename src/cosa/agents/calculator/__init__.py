"""
Everyday Calculator Agent — Intent-Dispatched Deterministic Calculations.

Handles unit conversions, price comparisons, and mortgage calculations
via LLM intent extraction + pure Python dispatch (no code generation).

Modules:
    agent.py            — CalculatorAgent (AgentBase subclass)
    xml_models.py       — CalcIntent (BaseXMLModel subclass)
    dispatcher.py       — dispatch() + format_result_for_voice()
    calc_operations.py  — Pure Python: convert(), compare_prices(), mortgage()
    conversion_tables.py — Unit conversion factors (dict-based)
"""
