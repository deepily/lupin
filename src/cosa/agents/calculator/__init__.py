"""
Everyday Calculator Agent — Intent-Dispatched Deterministic Calculations.

Handles arithmetic, unit conversions, price comparisons and mortgage calculations.
An LLM extracts the intent, then pure Python does the work. No code is generated.

Modules:
    - agent.py — CalculatorAgent (AgentBase subclass).
    - xml_models.py — CalcIntent (BaseXMLModel subclass).
    - dispatcher.py — dispatch() and format_result_for_voice().
    - calc_operations.py — Pure Python: arithmetic(), convert(), compare_prices(), mortgage().
    - conversion_tables.py — Unit conversion factors (dict-based).
"""
