# v0.20 interview story

The main lesson is not that every real-data experiment should produce a positive headline. The pipeline separates three questions that are often mixed together: did the data arrive correctly, was the historical information set valid, and did the promoted model actually improve the independent final window?

I therefore added a machine-readable evidence ledger after the network run. Each horizon is classified as a positive real result, a real negative result, a deployment fallback, or evidence-blocked. Every decision points to hashed Elexon/NESO reports and manifests. This means a later data refresh cannot silently replace the evidence behind an old application claim.

A useful example is a horizon where the model passed validation and was promoted but lost on the final window. The correct action is to preserve that as a real negative result, not retune on the final data or hide it inside a generic PASS/FAIL workflow status. Conversely, if the data or publication-time coverage is incomplete, I do not report the number at all.

The same separation applies to CV writing: only a complete positive real result can generate a new positive numerical bullet automatically. Negative/fallback evidence remains useful in a technical interview because it shows the deployment policy and evaluation design worked even when the model did not.
