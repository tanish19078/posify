"""Provision a reviewed Colab export into an ignored local model directory."""
import argparse
from pathlib import Path

from posify.provisioning import install_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', type=Path, default=Path('models/nameplate-v1'))
    args = parser.parse_args()
    manifest = install_bundle(args.bundle, args.output)
    print(f'Bundle verified and provisioned: {manifest}')
    print(f'POSIFY_DETECTOR_MANIFEST={manifest.resolve()}')
    print('Run scripts/verify_detector.py before enabling detect_ocr jobs.')


if __name__ == '__main__':
    main()
