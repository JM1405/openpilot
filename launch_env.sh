#!/usr/bin/env bash

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# models get lower priority than ui
# - ui is ~5ms
# - modeld is 20ms
# - DM is 10ms
# in order to run ui at 60fps (16.67ms), we need to allow
# it to preempt the model workloads. we have enough
# headroom for this until ui is moved to the CPU.
export QCOM_PRIORITY=12

if [ -z "$AGNOS_VERSION" ]; then
  export AGNOS_VERSION="18.4"
fi

export STAGING_ROOT="/data/safe_staging"

# Koranipilot B1 home reception: explicit install profile.
export SUNNYPILOT_UI=1
export KOREAN_PHONE_LOCAL=1
export KOREAN_PHONE_SETTINGS_WRITE=0
export KOREAN_PHONE_MODEL_CHANGE=1
export KOREAN_ROAD_INPUT=0
export KOREAN_DRIVING_STATUS=0
export KOREAN_MICI_UI=0
export KOREAN_LEAD_SOURCE=0
export KOREAN_LEAD_GROUND=0
export KOREAN_WIDE_LEAD=0
unset KOREAN_PHONE_CERT KOREAN_PHONE_KEY KOREAN_PHONE_BIND KOREAN_PHONE_AUTHORITY KOREAN_PHONE_PORT

# Road control candidate remains inactive until separately validated.
export KOREAN_ROAD_CONTROL=0
