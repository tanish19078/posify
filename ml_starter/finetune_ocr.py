"""Generate an upstream PaddleOCR fine-tune config; optionally launch its trainer."""
import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def label_images(path, root):
    result=set()
    for index,line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(),1):
        if not line.strip(): continue
        if '\t' not in line: raise ValueError(f'{path}:{index}: expected image-path TAB transcription')
        name,text=line.split('\t',1)
        image=(root/name).resolve()
        if not text.strip() or not image.is_relative_to(root) or not image.is_file():
            raise ValueError(f'{path}:{index}: missing image or empty transcription')
        result.add(hashlib.sha256(image.read_bytes()).hexdigest())
    if not result: raise ValueError('Label list is empty')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True,help='Trusted local checkout of official PaddleOCR')
    parser.add_argument('--config',required=True,help='Upstream recognition training config, relative to repo or absolute')
    parser.add_argument('--pretrained',required=True,help='Matching dynamic training checkpoint, not inference weights')
    parser.add_argument('--train-list',required=True)
    parser.add_argument('--val-list',required=True)
    parser.add_argument('--image-root',required=True,help='Recognition LINE crops, not entire nameplates')
    parser.add_argument('--output',required=True)
    parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--batch',type=int,default=32)
    parser.add_argument('--lr',type=float,default=1e-5)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.epochs<1 or args.batch<1 or args.lr<=0: parser.error('epochs, batch and learning rate must be positive')
    import yaml
    repo=Path(args.repo).resolve(); root=Path(args.image_root).resolve()
    config_path=Path(args.config)
    if not config_path.is_absolute(): config_path=repo/config_path
    config=yaml.safe_load(config_path.read_text())
    pretrained=Path(args.pretrained).resolve()
    if not pretrained.is_file() and not Path(str(pretrained)+'.pdparams').is_file():
        parser.error('Training checkpoint was not found')
    if label_images(args.train_list,root) & label_images(args.val_list,root):
        parser.error('Identical image crops occur in both train and validation lists')
    if not (repo/'tools/train.py').is_file(): parser.error('PaddleOCR tools/train.py was not found')
    if not all(key in config for key in ['Global','Train','Eval','Optimizer','Architecture']):
        parser.error('Expected an upstream PaddleOCR recognition training configuration')
    if config['Architecture'].get('model_type') != 'rec': parser.error('Use a recognition config, not a text detector config')
    dictionary=config['Global'].get('character_dict_path')
    if dictionary and not (repo/dictionary).is_file(): parser.error('Configured character dictionary was not found')
    output=Path(args.output).resolve(); output.mkdir(parents=True,exist_ok=True)
    target=output/'finetune.yml'
    if target.exists(): parser.error('Config already exists; use a fresh output directory')
    config['Global'].update(pretrained_model=str(pretrained),save_model_dir=str(output/'checkpoints'),
                            epoch_num=args.epochs,distributed=False)
    if dictionary: config['Global']['character_dict_path']=str((repo/dictionary).resolve())
    rate=config['Optimizer'].get('lr')
    if isinstance(rate,dict): rate['learning_rate']=args.lr
    else: config['Optimizer']['lr']=args.lr
    for phase,label in [('Train',args.train_list),('Eval',args.val_list)]:
        dataset=config[phase]['dataset']
        dataset.update(data_dir=str(root),label_file_list=[str(Path(label).resolve())],ratio_list=[1.0])
        loader=config[phase].setdefault('loader',{})
        loader.update(batch_size_per_card=args.batch,num_workers=2)
        if 'sampler' in config[phase] and isinstance(config[phase]['sampler'],dict):
            config[phase]['sampler']['first_bs']=args.batch
    target.write_text(yaml.safe_dump(config,sort_keys=False,allow_unicode=True))
    command=[sys.executable,'tools/train.py','-c',str(target)]
    print('Config generated:',target)
    print('Run from',repo,':', ' '.join(command))
    print('Checkpoint architecture and dictionary compatibility must be checked against the upstream model card.')
    if args.run: subprocess.run(command,cwd=repo,check=True)


if __name__=='__main__': main()
