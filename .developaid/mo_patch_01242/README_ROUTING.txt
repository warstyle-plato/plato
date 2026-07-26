Routing requirement confirmed 2026-07-26:
1. Try GlavAPU for every cadastral number, including 50: numbers.
2. If GlavAPU returns valid TEP, use GlavAPU (this covers New Moscow parcels with 50: cadastral prefixes).
3. Only when GlavAPU returns no usable result and the cadastral number starts with 50:, use the internal Moscow Region VRI/TEP calculator.
4. Non-50: failures must not be routed to the Moscow Region calculator.
