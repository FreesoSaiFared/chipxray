#!/usr/bin/env bash
# Download pinned inputs. First run writes SHA256SUMS; later runs verify against it.
set -e
cd "$(dirname "$0")"
PHY=20f1db053a0e6cb9f1c09d255c43bf42483041d0
PACS=fed196c2f4b46f28f67e197ddbc007acd9804d3b
mkdir -p blobs/espressif blobs/svd
for c in esp32 esp32s3 esp32c3 esp32c5 esp32c61; do
  [ -f blobs/espressif/${c}_librftest.a ] || curl -sfL -o blobs/espressif/${c}_librftest.a \
    "https://raw.githubusercontent.com/espressif/esp-phy-lib/$PHY/$c/librftest.a"
  [ -f blobs/svd/$c.svd ] || curl -sfL -o blobs/svd/$c.svd \
    "https://raw.githubusercontent.com/esp-rs/esp-pacs/$PACS/$c/svd/$c.base.svd"
done
if [ -f SHA256SUMS ]; then sha256sum -c --quiet SHA256SUMS && echo "inputs OK"
else sha256sum blobs/espressif/*.a blobs/svd/*.svd > SHA256SUMS && echo "wrote SHA256SUMS"; fi
