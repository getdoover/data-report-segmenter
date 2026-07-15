#!/bin/sh
# Build the processor deployment package (package.zip) for a PRO-type app.
#
# Mirrors sia_dra_dashboard/apps/dra_dashboard/build.sh: resolve the locked
# dependency set, install it flattened into packages_export for the Lambda
# runtime target (python3.13 / manylinux2014), then zip the flattened
# site-packages together with the src/ tree.
#
# No heavy deps are vendored: the CSV is rendered with the stdlib `csv`
# module, so pydoover (+ its deps) is the only thing in packages_export.

set -e

uv sync --quiet
uv export --frozen --no-dev --no-editable --quiet -o requirements.txt

rm -rf packages_export

uv pip install \
   --no-deps \
   --no-installer-metadata \
   --no-compile-bytecode \
   --python-platform x86_64-manylinux2014 \
   --python 3.13 \
   --quiet \
   --target packages_export \
   --refresh \
   -r requirements.txt

rm -f package.zip

cd packages_export
zip -rq ../package.zip .
cd ..

zip -rq package.zip src

echo "OK"
