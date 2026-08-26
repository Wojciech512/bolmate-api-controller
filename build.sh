#!/usr/bin/env bash

rm -rf dist || true
./env/bin/python -m build --wheel
rm -rf build || true
echo "Wheel built"