"""Copy digest-pinned pretrained OCR models from the installed package; no training."""
import argparse
from posify.neural_ocr import install_models

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--destination',default='models/ocr-ppv6')
args=parser.parse_args()
print('Provisioned local OCR models:',install_models(args.destination))
