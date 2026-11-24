# REFINERY Service Specification

## Overview
REFINERY is an AI audio post-processing platform specifically tuned for generative music services like Suno and Udio.
It handles high-frequency artifact restoration, stem separation/vocal enhancement, and broadcast-grade loudness mastering (-14 LUFS).

## Core Requirements
1. **Responsive Target**: 360px (mobile priority) / 768px (tablet) / 1200px (desktop) / 1600px+ (ultrawide).
2. **Design Theme**: Aurora Night (`#070B14`, `#0D1322`, accent gradients `#5EEAD4` -> `#818CF8` -> `#F0ABFC`).
3. **API Contract**:
   - `POST /api/jobs`
   - `GET /api/jobs/{id}` (1.5s polling)
   - `GET /api/jobs/{id}/original` & `/result`
   - `GET /api/jobs/{id}/download`
