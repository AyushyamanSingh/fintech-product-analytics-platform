"""AI analyst layer: grounded executive summaries and natural-language Q&A over the warehouse.

Design principle: the model never produces a number on its own. Summaries are written from a
numbered fact sheet computed by the pipeline and every number is machine-checked against the
facts it cites; Q&A answers must come from read-only SQL the model runs through a tool.
"""
