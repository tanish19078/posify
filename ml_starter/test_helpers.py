"""Lightweight helper tests; no model installation, inference or training."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from PIL import Image

from validate_dataset import inspect_dataset
from benchmark_ocr import distance
from prepare_multiclass import prepare_multiclass


class Helpers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for split,color in [('train','white'),('valid','blue'),('test','red')]:
            (self.root/split/'images').mkdir(parents=True)
            (self.root/split/'labels').mkdir(parents=True)
            Image.new('RGB',(100,100),color).save(self.root/split/'images'/'sample.png')
            (self.root/split/'labels'/'sample.txt').write_text('0 0.5 0.5 0.4 0.4\n')
        self.config=self.root/'data.yaml'
        self.config.write_text(yaml.safe_dump({'path':str(self.root),'train':'train/images','val':'valid/images',
                                              'test':'test/images','names':['nameplate']}))

    def test_valid(self):
        config,report=inspect_dataset(self.config)
        self.assertEqual(report['splits']['train']['images'],1)
        self.assertEqual(report['classes'],['nameplate'])
        self.assertTrue(Path(config['train']).is_absolute())

    def test_duplicate(self):
        (self.root/'valid/images/sample.png').write_bytes((self.root/'train/images/sample.png').read_bytes())
        with self.assertRaisesRegex(ValueError,'Duplicate image'): inspect_dataset(self.config)

    def test_group_leakage(self):
        groups=self.root/'groups.csv'
        groups.write_text('image,group_id\ntrain/images/sample.png,same\nvalid/images/sample.png,same\ntest/images/sample.png,other\n')
        with self.assertRaisesRegex(ValueError,'crosses'): inspect_dataset(self.config,groups)

    def test_missing_label(self):
        (self.root/'train/labels/sample.txt').unlink()
        with self.assertRaisesRegex(ValueError,'Missing label'): inspect_dataset(self.config)

    def test_invalid_boxes(self):
        for label in ['1 .5 .5 .4 .4','0 nan .5 .4 .4','0 0 .5 1 .4','0 .5 .5 0 .4']:
            (self.root/'train/labels/sample.txt').write_text(label)
            with self.assertRaises(ValueError): inspect_dataset(self.config)

    def test_no_download_commands(self):
        cfg=yaml.safe_load(self.config.read_text()); cfg['download']='echo unsafe'
        self.config.write_text(yaml.safe_dump(cfg))
        with self.assertRaisesRegex(ValueError,'download'): inspect_dataset(self.config)

    def test_label_changes_change_fingerprint(self):
        before=inspect_dataset(self.config)[1]['fingerprint']
        (self.root/'train/labels/sample.txt').write_text('0 .6 .6 .2 .2')
        after=inspect_dataset(self.config)[1]['fingerprint']
        self.assertNotEqual(before,after)

    def test_edit_distance(self):
        self.assertEqual(distance('S-001','S-OO1'),2)
        self.assertEqual(distance('ABC','ABC'),0)
        self.assertEqual(distance('','ABC'),3)

    def test_ocr_config_generation_does_not_launch_training(self):
        repo=self.root/'PaddleOCR'; (repo/'tools').mkdir(parents=True)
        (repo/'tools/train.py').write_text("raise RuntimeError('Should not run')")
        (repo/'dict.txt').write_text('A\nB\n')
        cfg=repo/'recognition.yml'
        cfg.write_text(yaml.safe_dump({'Global':{'character_dict_path':'dict.txt'},
            'Architecture':{'model_type':'rec'},'Optimizer':{'lr':{'learning_rate':.001}},
            'Train':{'dataset':{},'loader':{}},'Eval':{'dataset':{},'loader':{}}}))
        checkpoint=self.root/'pretrained.pdparams'; checkpoint.write_bytes(b'fixture-not-a-real-checkpoint')
        train=self.root/'train.txt'; train.write_text('train/images/sample.png\tA\n')
        val=self.root/'val.txt'; val.write_text('valid/images/sample.png\tB\n')
        script=Path(__file__).parent/'finetune_ocr.py'
        run=subprocess.run([sys.executable,str(script),'--repo',str(repo),'--config',str(cfg),
            '--pretrained',str(checkpoint),'--train-list',str(train),'--val-list',str(val),
            '--image-root',str(self.root),'--output',str(self.root/'out')],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        generated=yaml.safe_load((self.root/'out/finetune.yml').read_text())
        self.assertEqual(generated['Global']['epoch_num'],20)
        self.assertEqual(generated['Optimizer']['lr']['learning_rate'],1e-5)

    def test_prepare_multiclass_remap_and_merge(self):
        src_a = self.root / 'src_nameplate'
        src_b = self.root / 'src_equipment'
        colors_a = {'train': (10, 20, 30), 'valid': (40, 50, 60), 'test': (70, 80, 90)}
        colors_b = {'train': (15, 25, 35), 'valid': (45, 55, 65), 'test': (75, 85, 95)}
        for split in ['train', 'valid', 'test']:
            (src_a / split / 'images').mkdir(parents=True)
            (src_a / split / 'labels').mkdir(parents=True)
            Image.new('RGB', (120, 120), colors_a[split]).save(src_a / split / 'images' / f'{split}_a.png')
            (src_a / split / 'labels' / f'{split}_a.txt').write_text('0 0.5 0.5 0.2 0.2\n')

            (src_b / split / 'images').mkdir(parents=True)
            (src_b / split / 'labels').mkdir(parents=True)
            Image.new('RGB', (120, 120), colors_b[split]).save(src_b / split / 'images' / f'{split}_b.png')
            # Class 0 = '0' (pump), Class 1 = 'open' (valve), Class 2 = 'close' (valve)
            (src_b / split / 'labels' / f'{split}_b.txt').write_text('0 0.3 0.3 0.2 0.2\n1 0.7 0.7 0.2 0.2\n')
        (src_a / 'data.yaml').write_text(yaml.safe_dump({
            'path': str(src_a), 'train': 'train/images', 'val': 'valid/images', 'test': 'test/images',
            'names': ['nameplate'],
        }))
        (src_b / 'data.yaml').write_text(yaml.safe_dump({
            'path': str(src_b), 'train': 'train/images', 'val': 'valid/images', 'test': 'test/images',
            'names': ['0', 'open', 'close'],
        }))
        merged_dir = self.root / 'merged_dataset'
        yaml_out, report = prepare_multiclass(
            sources=[
                {'path': str(src_a), 'class_map': {'nameplate': 'nameplate'}},
                {'path': str(src_b), 'class_map': {'0': 'pump', 'open': 'valve', 'close': 'valve'}},
            ],
            target_classes=['nameplate', 'pump', 'valve'],
            output_dir=str(merged_dir),
        )
        self.assertTrue(yaml_out.is_file())
        self.assertEqual(report['classes'], ['nameplate', 'pump', 'valve'])
        self.assertEqual(report['splits']['train']['images'], 2)
        self.assertEqual(report['splits']['train']['objects'], [1, 1, 1])

    def test_prepare_multiclass_auto_splits_when_val_test_missing(self):
        src = self.root / 'train_only'
        (src / 'train' / 'images').mkdir(parents=True)
        (src / 'train' / 'labels').mkdir(parents=True)
        for idx in range(10):
            Image.new('RGB', (80, 80), (idx * 20, 100, 150)).save(src / 'train' / 'images' / f'img_{idx}.png')
            cls = idx % 2
            (src / 'train' / 'labels' / f'img_{idx}.txt').write_text(f'{cls} 0.5 0.5 0.3 0.3\n')
        (src / 'data.yaml').write_text(yaml.safe_dump({
            'path': str(src), 'train': 'train/images', 'names': ['nameplate', 'motor'],
        }))
        out_dir = self.root / 'auto_split_out'
        _, report = prepare_multiclass(
            sources=[{'path': str(src)}],
            target_classes=['nameplate', 'motor'],
            output_dir=str(out_dir),
            ensure_splits=True,
        )
        self.assertEqual(
            report['splits']['train']['images'] + report['splits']['val']['images'] + report['splits']['test']['images'],
            10,
        )
        self.assertGreaterEqual(report['splits']['val']['images'], 1)
        self.assertGreaterEqual(report['splits']['test']['images'], 1)


if __name__=='__main__': unittest.main()
