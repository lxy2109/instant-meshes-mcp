from typing import Any, Dict, Optional
import subprocess
import os
import tempfile
import shutil
import requests
from mcp.server.fastmcp import FastMCP
import trimesh
import urllib.parse
import datetime
import psutil
import pymeshlab

mcp = FastMCP("instant_meshes")

INSTANT_MESHES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Instant Meshes.exe")

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_remesh")
os.makedirs(OUTPUT_DIR, exist_ok=True)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "instant_meshes.log")

def is_url(path: str) -> bool:
    """判断路径是否为URL"""
    return path.startswith("http://") or path.startswith("https://")

def get_temp_file(suffix: str) -> str:
    """在temp目录下创建唯一临时文件名，不创建文件，仅返回路径"""
    fd, path = tempfile.mkstemp(suffix=suffix, dir=TEMP_DIR)
    os.close(fd)
    return path

def download_to_temp(url: str) -> str:
    """
    下载远程文件到本地temp文件夹，返回临时文件路径。
    只保留主文件名和后缀，去除URL参数，避免Windows非法字符。
    Args:
        url (str): 远程文件URL
    Returns:
        str: 本地临时文件路径
    Raises:
        requests.RequestException: 下载失败时抛出
    """
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path)  # 只取路径部分
    suffix = os.path.splitext(base)[-1] if '.' in base else ''
    temp_path = get_temp_file(suffix)
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(temp_path, 'wb') as tmp:
        for chunk in response.iter_content(chunk_size=8192):
            tmp.write(chunk)
    return temp_path

def move_and_cleanup(src: str, dst: str) -> None:
    """
    移动文件到目标并删除源文件。
    Args:
        src (str): 源文件路径
        dst (str): 目标文件路径
    """
    shutil.move(src, dst)
    if os.path.exists(src):
        os.remove(src)

def glb_to_obj(glb_path: str, obj_path: str) -> None:
    """
    用trimesh将GLB转OBJ，保留基本几何和材质。
    Args:
        glb_path (str): 输入GLB文件路径
        obj_path (str): 输出OBJ文件路径
    Raises:
        RuntimeError: 转换失败时抛出
    """
    mesh = trimesh.load(glb_path, force='mesh')
    mesh.export(obj_path)

def obj_to_glb(obj_path: str, glb_path: str) -> None:
    """
    用trimesh将OBJ转GLB。
    Args:
        obj_path (str): 输入OBJ文件路径
        glb_path (str): 输出GLB文件路径
    Raises:
        RuntimeError: 转换失败时抛出
    """
    mesh = trimesh.load(obj_path, force='mesh')
    mesh.export(glb_path)

def run_instant_meshes(
    obj_in: str,
    obj_out: str,
    target_faces: int,
    extra_options: Optional[Dict[str, Any]] = None
) -> None:
    """
    调用Instant Meshes命令行进行重拓扑，支持所有官方参数。
    每次运行日志输出到 logs/instant_meshes_YYYYmmdd_HHMMSS.log，避免锁定。
    remesh完成后强制结束所有Instant Meshes.exe进程。
    Args:
        obj_in (str): 输入OBJ文件路径
        obj_out (str): 输出OBJ文件路径
        target_faces (int): 目标面数
        extra_options (dict): 其他命令行参数，如{"-d": True, "-t": 4}
    Raises:
        subprocess.CalledProcessError: 命令行执行失败时抛出
    """
    cmd = [
        INSTANT_MESHES_PATH,
        "-i", obj_in,
        "-o", obj_out,
        "--faces", str(target_faces)
    ]
    if extra_options:
        for k, v in extra_options.items():
            if isinstance(v, bool):
                if v:
                    cmd.append(str(k))
            else:
                cmd.extend([str(k), str(v)])
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(LOG_DIR, f"instant_meshes_{timestamp}.log")
    proc = None
    try:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"\n===== {timestamp} Instant Meshes Run =====\n")
            proc = subprocess.Popen(cmd, stdout=logf, stderr=logf)
            proc.communicate()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
    finally:
        # 强制杀掉所有残留的 Instant Meshes.exe 进程
        for p in psutil.process_iter(['name', 'exe']):
            try:
                if p.info['name'] and 'Instant Meshes.exe' in p.info['name']:
                    p.kill()
            except Exception:
                pass

def auto_simplify_mesh(input_path: str, max_faces: int = 100000) -> str:
    """
    如果模型面数超过max_faces，自动用pymeshlab简化到max_faces以内，返回简化后模型路径（obj）。
    否则返回原始路径。
    """
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_path)
    n_faces = ms.current_mesh().face_number()
    if n_faces > max_faces:
        ms.meshing_decimation_quadric_edge_collapse(targetfacenum=max_faces)
        simplified_path = input_path.replace('.obj', '_simplified.obj').replace('.glb', '_simplified.obj')
        ms.save_current_mesh(simplified_path)
        return simplified_path
    return input_path

def force_triangle_simplify(input_path: str, target_triangles: int) -> str:
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_path)
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=target_triangles)
    simplified_path = input_path.replace('.obj', '_tri.obj')
    ms.save_current_mesh(simplified_path)
    return simplified_path

def safe_copy(src, dst_dir):
    import os, shutil
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src, dst)
    return dst

def restore_obj_material(obj_path: str, original_obj_path: str):
    """
    将原始OBJ的mtl和贴图引用复制到新OBJ，修正mtllib和usemtl，保证贴图不丢失。
    """
    orig_dir = os.path.dirname(original_obj_path)
    with open(original_obj_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    mtl_files = [line.split()[1] for line in lines if line.lower().startswith('mtllib')]
    if not mtl_files:
        return
    mtl_file = mtl_files[0]
    orig_mtl_path = os.path.join(orig_dir, mtl_file)
    new_dir = os.path.dirname(obj_path)
    safe_copy(orig_mtl_path, new_dir)
    # 复制贴图文件
    with open(orig_mtl_path, 'r', encoding='utf-8') as f:
        mtl_lines = f.readlines()
    for line in mtl_lines:
        if line.lower().startswith('map_kd'):
            tex_file = line.split()[1]
            orig_tex_path = os.path.join(orig_dir, tex_file)
            safe_copy(orig_tex_path, new_dir)
    # 修正新OBJ的mtllib引用
    with open(obj_path, 'r', encoding='utf-8') as f:
        obj_lines = f.readlines()
    new_obj_lines = []
    mtl_written = False
    for line in obj_lines:
        if line.lower().startswith('mtllib'):
            if not mtl_written:
                new_obj_lines.append(f'mtllib {mtl_file}\n')
                mtl_written = True
        else:
            new_obj_lines.append(line)
    if not mtl_written:
        new_obj_lines.insert(0, f'mtllib {mtl_file}\n')
    with open(obj_path, 'w', encoding='utf-8') as f:
        f.writelines(new_obj_lines)

def get_original_name(input_model: str) -> str:
    # 支持本地路径和URL
    if input_model.startswith('http://') or input_model.startswith('https://'):
        path = urllib.parse.urlparse(input_model).path
        return os.path.basename(path)
    else:
        return os.path.basename(input_model)

@mcp.tool()
async def remesh_model(
    input_model: str,
    output_model: str = None,
    target_faces: int = 5000,
    preserve_uv: bool = True,
    options: Optional[Dict[str, Any]] = None
) -> str:
    """
    用Instant Meshes对模型进行重拓扑/简化，支持所有命令行参数和URL输入输出。

    Args:
        input_model (str): 输入模型路径（支持GLB/OBJ或URL）
        output_model (str): 输出模型路径（OBJ/GLB或本地路径/URL）
        target_faces (int): 目标面数
        preserve_uv (bool): 是否尽量保留UV（仅限OBJ流程）
        options (dict): 其他Instant Meshes命令行参数（如{"-d": True, "-t": 4}）
    Returns:
        str: 输出模型路径
    Raises:
        RuntimeError: 处理失败时抛出
    """
    temp_files = []
    try:
        # 1. 处理输入模型（支持URL）
        if is_url(input_model):
            local_input = download_to_temp(input_model)
            temp_files.append(local_input)
        else:
            local_input = input_model

        # 2. 若输入为GLB，先转OBJ
        if local_input.lower().endswith(".glb"):
            obj_in = get_temp_file(".obj")
            glb_to_obj(local_input, obj_in)
            temp_files.append(obj_in)
        else:
            obj_in = local_input

        # 自动简化大模型（已移除，直接用原始模型）
        # simplified_obj_in = auto_simplify_mesh(obj_in, max_faces=500000)
        # if simplified_obj_in != obj_in:
        #     temp_files.append(simplified_obj_in)
        #     obj_in = simplified_obj_in

        # 3. 输出先到临时文件（obj）
        temp_output = get_temp_file(".obj")
        temp_files.append(temp_output)

        # 4. Instant Meshes重拓扑（只用--faces参数）
        options = options or {}
        run_instant_meshes(obj_in, temp_output, target_faces, extra_options=options)
        # 修复材质引用
        restore_obj_material(temp_output, obj_in)

        final_obj = temp_output  # 直接用 Instant Meshes 输出

        # 5. 输出为GLB，trimesh自动打包贴图
        temp_glb = get_temp_file(".glb")
        obj_to_glb(final_obj, temp_glb)
        temp_files.append(temp_glb)
        final_output = temp_glb

        # 6. 输出路径与原模型同名
        orig_name = get_original_name(input_model)
        output_name = os.path.splitext(orig_name)[0] + ".glb"
        output_model = os.path.join(OUTPUT_DIR, output_name)
        move_and_cleanup(final_output, output_model)
        return output_model
    finally:
        # 清理所有临时文件
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

if __name__ == "__main__":
    mcp.run(transport='stdio')