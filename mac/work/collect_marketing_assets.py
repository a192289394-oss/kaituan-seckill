"""Download only public, officially referenced live-seckill route JS assets."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

root=Path(__file__).resolve().parent/'official-assets-20261014'
runtime=(root/'marketing-e7f1a2c5.js').read_text()
route=(root/'marketing-62e7e448.js').read_text()
begin=route.index('/live-seckill/edit');end=route.index('then(n.bind',begin)
ids=re.findall(r'n\.e\("(\d+)"\)',route[begin:end])
mapping=dict(re.findall(r'(\d+):"([0-9a-f]{8})"',runtime))
def download(chunk):
    if chunk not in mapping:return chunk,'shared'
    path=root/f'marketing-chunk-{chunk}.js'
    if path.exists():return chunk,'cached'
    url='https://lf-cdn-tos.bytescm.com/obj/static/life_service/fe_ls_marketing_pc/tools_merchant_new_pc/resource/async/'+mapping[chunk]+'.js'
    r=subprocess.run(['curl','--fail','--silent','--show-error','--max-time','25',url,'-o',str(path)],capture_output=True)
    return chunk,'ok' if r.returncode==0 else 'download failed'
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        for chunk,state in pool.map(download,ids):print(chunk,state)
