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
import json
import time
import signal

mcp = FastMCP("instant_meshes")

INSTANT_MESHES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Instant Meshes.exe")

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_remesh")
os.makedirs(OUTPUT_DIR, exist_ok=True)

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archives")
os.makedirs(ARCHIVE_DIR, exist_ok=True)

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

def copy_obj_package_to_temp(obj_path: str, additional_files: list = None) -> str:
    """
    将OBJ文件及其相关文件（MTL、贴图）复制到temp目录。
    Args:
        obj_path (str): 主OBJ文件路径
        additional_files (list): 额外的文件路径列表（MTL、贴图等）
    Returns:
        str: temp目录中的OBJ文件路径
    Raises:
        RuntimeError: 复制失败时抛出
    """
    if not os.path.exists(obj_path):
        raise RuntimeError(f"OBJ file not found: {obj_path}")
    
    # 复制主OBJ文件到temp
    obj_basename = os.path.basename(obj_path)
    temp_obj_path = os.path.join(TEMP_DIR, obj_basename)
    shutil.copy2(obj_path, temp_obj_path)
    
    # 自动查找并复制相关文件
    obj_dir = os.path.dirname(obj_path)
    obj_name = os.path.splitext(obj_basename)[0]
    
    # 查找同名MTL文件
    mtl_path = os.path.join(obj_dir, f"{obj_name}.mtl")
    if os.path.exists(mtl_path):
        temp_mtl_path = os.path.join(TEMP_DIR, f"{obj_name}.mtl")
        shutil.copy2(mtl_path, temp_mtl_path)
        
        # 从MTL文件中提取贴图文件引用并复制
        try:
            with open(mtl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line_lower = line.lower().strip()
                    if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal')):
                        parts = line.split()
                        if len(parts) > 1:
                            tex_file = parts[-1]  # 取最后一个部分作为文件名
                            # 处理可能的路径分隔符
                            tex_file = tex_file.replace('\\', '/').split('/')[-1]
                            orig_tex_path = os.path.join(obj_dir, tex_file)
                            if os.path.exists(orig_tex_path):
                                temp_tex_path = os.path.join(TEMP_DIR, tex_file)
                                shutil.copy2(orig_tex_path, temp_tex_path)
        except Exception:
            pass
    
    # 复制额外指定的文件
    if additional_files:
        for file_path in additional_files:
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                temp_file_path = os.path.join(TEMP_DIR, filename)
                shutil.copy2(file_path, temp_file_path)
    
    # 查找OBJ文件中引用的MTL文件
    try:
        with open(obj_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.lower().startswith('mtllib'):
                    parts = line.split()
                    if len(parts) > 1:
                        referenced_mtl = parts[1]
                        # 处理可能的路径分隔符
                        referenced_mtl = referenced_mtl.replace('\\', '/').split('/')[-1]
                        referenced_mtl_path = os.path.join(obj_dir, referenced_mtl)
                        if os.path.exists(referenced_mtl_path):
                            temp_referenced_mtl = os.path.join(TEMP_DIR, referenced_mtl)
                            if not os.path.exists(temp_referenced_mtl):
                                shutil.copy2(referenced_mtl_path, temp_referenced_mtl)
                            
                            # 从引用的MTL文件中复制贴图
                            try:
                                with open(referenced_mtl_path, 'r', encoding='utf-8') as mtl_f:
                                    for mtl_line in mtl_f:
                                        mtl_line_lower = mtl_line.lower().strip()
                                        if mtl_line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal')):
                                            mtl_parts = mtl_line.split()
                                            if len(mtl_parts) > 1:
                                                tex_file = mtl_parts[-1]
                                                tex_file = tex_file.replace('\\', '/').split('/')[-1]
                                                orig_tex_path = os.path.join(obj_dir, tex_file)
                                                if os.path.exists(orig_tex_path):
                                                    temp_tex_path = os.path.join(TEMP_DIR, tex_file)
                                                    if not os.path.exists(temp_tex_path):
                                                        shutil.copy2(orig_tex_path, temp_tex_path)
                            except Exception:
                                pass
                        break
    except Exception:
        pass
    
    return temp_obj_path

def copy_folder_to_temp(folder_path: str) -> str:
    """
    将包含OBJ文件包的文件夹复制到temp目录，并返回主OBJ文件路径。
    Args:
        folder_path (str): 包含OBJ文件包的文件夹路径
    Returns:
        str: temp目录中的主OBJ文件路径
    Raises:
        RuntimeError: 复制失败或找不到OBJ文件时抛出
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        raise RuntimeError(f"Folder not found or not a directory: {folder_path}")
    
    # 查找文件夹中的OBJ文件
    obj_files = []
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.obj'):
            obj_files.append(filename)
    
    if not obj_files:
        raise RuntimeError(f"No OBJ files found in folder: {folder_path}")
    
    if len(obj_files) > 1:
        # 如果有多个OBJ文件，选择第一个，但记录警告
        main_obj = obj_files[0]
        print(f"Warning: Multiple OBJ files found, using: {main_obj}")
    else:
        main_obj = obj_files[0]
    
    # 复制文件夹中的所有文件到temp目录
    copied_files = []
    try:
        for filename in os.listdir(folder_path):
            src_path = os.path.join(folder_path, filename)
            if os.path.isfile(src_path):
                dst_path = os.path.join(TEMP_DIR, filename)
                shutil.copy2(src_path, dst_path)
                copied_files.append(dst_path)
        
        # 返回主OBJ文件在temp目录中的路径
        temp_obj_path = os.path.join(TEMP_DIR, main_obj)
        return temp_obj_path
        
    except Exception as e:
        # 清理已复制的文件
        for copied_file in copied_files:
            if os.path.exists(copied_file):
                try:
                    os.remove(copied_file)
                except Exception:
                    pass
        raise RuntimeError(f"Failed to copy folder to temp: {e}")

def analyze_obj_folder(folder_path: str) -> Dict[str, Any]:
    """
    分析包含OBJ文件包的文件夹，返回文件清单和关系。
    Args:
        folder_path (str): 文件夹路径
    Returns:
        dict: 包含文件分析结果的字典
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        return {"error": f"Folder not found or not a directory: {folder_path}"}
    
    result = {
        "folder_path": folder_path,
        "obj_files": [],
        "mtl_files": [],
        "texture_files": [],
        "other_files": [],
        "relationships": [],
        "warnings": [],
        "errors": []
    }
    
    # 分类文件
    texture_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tiff', '.dds', '.hdr', '.exr']
    
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path):
            lower_name = filename.lower()
            if lower_name.endswith('.obj'):
                result["obj_files"].append(filename)
            elif lower_name.endswith('.mtl'):
                result["mtl_files"].append(filename)
            elif any(lower_name.endswith(ext) for ext in texture_extensions):
                result["texture_files"].append(filename)
            else:
                result["other_files"].append(filename)
    
    # 分析文件关系
    for obj_file in result["obj_files"]:
        obj_path = os.path.join(folder_path, obj_file)
        relationship = {
            "obj_file": obj_file,
            "referenced_mtl": [],
            "missing_mtl": [],
            "available_textures": [],
            "missing_textures": []
        }
        
        # 读取OBJ文件中的MTL引用
        try:
            with open(obj_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.lower().startswith('mtllib'):
                        parts = line.split()
                        if len(parts) > 1:
                            mtl_name = parts[1].replace('\\', '/').split('/')[-1]
                            relationship["referenced_mtl"].append(mtl_name)
                            
                            # 检查MTL文件是否存在
                            if mtl_name not in result["mtl_files"]:
                                relationship["missing_mtl"].append(mtl_name)
        except Exception:
            result["errors"].append(f"Failed to read OBJ file: {obj_file}")
            continue
        
        # 分析MTL文件中的贴图引用
        for mtl_file in result["mtl_files"]:
            if mtl_file in relationship["referenced_mtl"]:
                mtl_path = os.path.join(folder_path, mtl_file)
                try:
                    with open(mtl_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line_lower = line.lower().strip()
                            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal')):
                                parts = line.split()
                                if len(parts) > 1:
                                    tex_name = parts[-1].replace('\\', '/').split('/')[-1]
                                    if tex_name in result["texture_files"]:
                                        if tex_name not in relationship["available_textures"]:
                                            relationship["available_textures"].append(tex_name)
                                    else:
                                        if tex_name not in relationship["missing_textures"]:
                                            relationship["missing_textures"].append(tex_name)
                except Exception:
                    result["errors"].append(f"Failed to read MTL file: {mtl_file}")
        
        result["relationships"].append(relationship)
    
    # 生成警告
    if not result["obj_files"]:
        result["warnings"].append("No OBJ files found in folder")
    elif len(result["obj_files"]) > 1:
        result["warnings"].append(f"Multiple OBJ files found: {result['obj_files']}")
    
    if not result["mtl_files"]:
        result["warnings"].append("No MTL files found in folder")
    
    if not result["texture_files"]:
        result["warnings"].append("No texture files found in folder")
    
    return result

def process_obj_with_materials(obj_path: str, additional_files: list = None) -> str:
    """
    处理OBJ文件及其材质文件，确保所有相关文件都在temp目录中。
    支持单个OBJ文件、文件列表或整个文件夹。
    Args:
        obj_path (str): OBJ文件路径、文件夹路径（可以是URL或本地路径）
        additional_files (list): 额外的文件路径列表
    Returns:
        str: temp目录中的OBJ文件路径
    """
    temp_files = []
    
    try:
        # 检查是否为文件夹
        if os.path.isdir(obj_path):
            # 文件夹模式：复制整个文件夹到temp
            return copy_folder_to_temp(obj_path)
        
        # 处理主OBJ文件
        if is_url(obj_path):
            local_obj = download_to_temp(obj_path)
            temp_files.append(local_obj)
        else:
            # 本地文件，复制整个OBJ包到temp目录
            local_obj = copy_obj_package_to_temp(obj_path, additional_files)
        
        # 处理额外的文件（如果是URL）
        if additional_files:
            for file_path in additional_files:
                if is_url(file_path):
                    downloaded_file = download_to_temp(file_path)
                    temp_files.append(downloaded_file)
        
        return local_obj
        
    except Exception as e:
        # 清理已下载的临时文件
        for temp_file in temp_files:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
        raise RuntimeError(f"Failed to process OBJ package: {e}")

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
    使用trimesh将OBJ文件转换为GLB文件
    """
    import trimesh
    import time
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(LOG_DIR, f"obj_to_glb_{timestamp}.log")
    
    with open(log_file, "w", encoding="utf-8") as logf:
        logf.write(f"Starting OBJ to GLB conversion\n")
        logf.write(f"Input OBJ: {obj_path}\n")
        logf.write(f"Output GLB: {glb_path}\n")
        logf.write(f"File exists: {os.path.exists(obj_path)}\n")
        if os.path.exists(obj_path):
            logf.write(f"File size: {os.path.getsize(obj_path)} bytes\n")
    
    try:
        start_time = time.time()
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Loading mesh with trimesh...\n")
        
        mesh = trimesh.load(obj_path)
        
        load_time = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Mesh loaded in {load_time:.2f} seconds\n")
            logf.write(f"Mesh type: {type(mesh)}\n")
        
        if hasattr(mesh, 'vertices'):
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Mesh vertices: {len(mesh.vertices)}\n")
                logf.write(f"Mesh faces: {len(mesh.faces) if hasattr(mesh, 'faces') else 'N/A'}\n")
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Starting GLB export...\n")
        
        export_start = time.time()
        mesh.export(glb_path)
        export_time = time.time() - export_start
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"GLB export completed in {export_time:.2f} seconds\n")
            logf.write(f"Output file exists: {os.path.exists(glb_path)}\n")
            if os.path.exists(glb_path):
                logf.write(f"Output file size: {os.path.getsize(glb_path)} bytes\n")
        
        total_time = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Total conversion time: {total_time:.2f} seconds\n")
            logf.write("OBJ to GLB conversion completed successfully\n")
            
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"ERROR during OBJ to GLB conversion: {e}\n")
        raise RuntimeError(f"OBJ to GLB conversion failed: {e}")

def get_model_scale(obj_path: str) -> float:
    """
    获取模型的包围盒对角线长度，用于计算合适的边长参数。
    Args:
        obj_path (str): OBJ文件路径
    Returns:
        float: 包围盒对角线长度
    """
    try:
        mesh = trimesh.load(obj_path, force='mesh')
        bounds = mesh.bounds
        diagonal = ((bounds[1] - bounds[0]) ** 2).sum() ** 0.5
        return diagonal
    except Exception:
        return 1.0  # 默认值

def calculate_edge_length(obj_path: str, target_faces: int) -> float:
    """
    根据模型尺寸和目标面数计算合适的边长。
    Args:
        obj_path (str): OBJ文件路径
        target_faces (int): 目标面数
    Returns:
        float: 推荐的边长
    """
    scale = get_model_scale(obj_path)
    # 根据目标面数估算合适的边长
    # 假设四面体网格，边长与面数平方根成反比
    edge_length = scale / (target_faces ** 0.5 * 10)
    # 限制边长范围，避免过大或过小
    edge_length = max(0.001, min(edge_length, scale * 0.1))
    return edge_length

def repair_mesh_with_pymeshlab(obj_path: str) -> str:
    """
    使用pymeshlab修复网格破洞和其他问题。
    Args:
        obj_path (str): 输入OBJ文件路径
    Returns:
        str: 修复后的OBJ文件路径
    """
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(obj_path)
    
    # 移除重复顶点
    ms.meshing_remove_duplicate_vertices()
    
    # 移除重复面
    ms.meshing_remove_duplicate_faces()
    
    # 移除零面积面
    ms.meshing_remove_null_faces()
    
    # 移除非流形边
    ms.meshing_remove_non_manifold_edges()
    
    # 修复小破洞（自适应大小）
    try:
        ms.meshing_close_holes(maxholesize=30)
    except Exception:
        # 如果自动修复失败，尝试更小的破洞
        try:
            ms.meshing_close_holes(maxholesize=10)
        except Exception:
            pass  # 如果仍然失败，继续处理
    
    # 平滑网格，减少噪声
    try:
        ms.apply_coord_laplacian_smoothing(stepsmoothnum=3, cotangentweight=False)
    except Exception:
        pass
    
    # 保存修复后的网格
    repaired_path = obj_path.replace('.obj', '_repaired.obj')
    ms.save_current_mesh(repaired_path)
    return repaired_path

def run_instant_meshes(
    obj_in: str,
    obj_out: str,
    target_faces: int,
    extra_options: Optional[Dict[str, Any]] = None,
    mode: str = "balanced"
) -> None:
    """
    调用Instant Meshes命令行进行重拓扑，支持所有官方参数。
    自动计算合适的边长参数，减少破洞和过细网格问题。
    每次运行日志输出到 logs/instant_meshes_YYYYmmdd_HHMMSS.log，避免锁定。
    remesh完成后强制结束所有Instant Meshes.exe进程。
    Args:
        obj_in (str): 输入OBJ文件路径
        obj_out (str): 输出OBJ文件路径
        target_faces (int): 目标面数
        extra_options (dict): 其他命令行参数，如{"-d": True, "-t": 4}
        mode (str): 重拓扑模式
    Raises:
        subprocess.CalledProcessError: 命令行执行失败时抛出
    """
    # 计算合适的边长参数
    edge_length = calculate_edge_length(obj_in, target_faces)
    
    # 根据模式调整参数（注意：--scale和--faces不能同时使用）
    if mode == "fine":
        # 精细模式：使用面数控制，添加更多质量参数
        cmd = [
            INSTANT_MESHES_PATH,
            "-i", obj_in,
            "-o", obj_out,
            "--faces", str(target_faces),
            "-d",  # 确定性模式
            "-b",  # 边界对齐
            "-c"   # 纯四边形网格
        ]
    elif mode == "coarse":
        # 粗糙模式：减少目标面数
        target_faces = int(target_faces * 0.8)  # 实际目标面数减少20%
        cmd = [
            INSTANT_MESHES_PATH,
            "-i", obj_in,
            "-o", obj_out,
            "--faces", str(target_faces),
            "-d"  # 只使用确定性模式
        ]
    elif mode == "fix_holes":
        # 修复破洞模式：专注于修复拓扑
        cmd = [
            INSTANT_MESHES_PATH,
            "-i", obj_in,
            "-o", obj_out,
            "--faces", str(target_faces),
            "-d",  # 确定性模式
            "-b",  # 边界对齐
            "-s", "2"  # 更多的平滑迭代
        ]
    else:  # balanced mode (default)
        cmd = [
            INSTANT_MESHES_PATH,
            "-i", obj_in,
            "-o", obj_out,
            "--faces", str(target_faces),
            "-d",  # 确定性模式，结果更稳定
            "-b"   # 边界对齐，减少边界破洞
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
            logf.write(f"Edge length: {edge_length}\n")
            logf.write(f"Target faces: {target_faces}\n")
            logf.write(f"Command: {' '.join(cmd)}\n")
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

def progressive_simplify(input_path: str, target_faces: int, preserve_boundaries: bool = True) -> str:
    """
    渐进式简化，避免一次性大幅减面导致模型破碎。
    Args:
        input_path (str): 输入OBJ文件路径
        target_faces (int): 目标面数
        preserve_boundaries (bool): 是否保持边界特征
    Returns:
        str: 简化后的OBJ文件路径
    """
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(input_path)
    
    original_faces = ms.current_mesh().face_number()
    
    # 如果已经小于目标面数，直接返回
    if original_faces <= target_faces:
        return input_path
    
    reduction_ratio = target_faces / original_faces
    
    # 如果减面比例超过50%，进行渐进式简化
    if reduction_ratio < 0.5:
        # 分步简化，每次最多减少50%
        current_faces = original_faces
        step = 1
        max_steps = 10  # 最大步数限制，防止无限循环
        
        # 记录处理过程到日志
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(LOG_DIR, f"progressive_simplify_{timestamp}.log")
        with open(log_file, "w", encoding="utf-8") as logf:
            logf.write(f"Progressive simplification started\n")
            logf.write(f"Original faces: {original_faces}\n")
            logf.write(f"Target faces: {target_faces}\n")
            logf.write(f"Reduction ratio: {reduction_ratio:.2%}\n")
        
        start_time = time.time()
        timeout_seconds = 300  # 5分钟超时
        
        while current_faces > target_faces * 1.1 and step <= max_steps:  # 留10%缓冲，限制最大步数
            # 检查超时
            if time.time() - start_time > timeout_seconds:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Breaking: timeout after {timeout_seconds} seconds\n")
                break
            prev_faces = current_faces  # 记录上一次的面数
            next_target = max(target_faces, int(current_faces * 0.6))  # 每步减少40%
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Step {step}: current_faces={current_faces}, next_target={next_target}\n")
            
            # 预处理：修复和清理网格
            if step == 1:
                try:
                    ms.meshing_remove_duplicate_vertices()
                    ms.meshing_remove_duplicate_faces()
                    ms.meshing_remove_null_faces()
                except Exception:
                    pass
            
            # 保守的简化参数
            try:
                ms.meshing_decimation_quadric_edge_collapse(
                    targetfacenum=next_target,
                    preserveboundary=preserve_boundaries,
                    preservenormal=True,
                    preservetopology=True,
                    optimalplacement=True,
                    planarquadric=False,  # 关闭平面二次型，更保守
                    qualityweight=False,  # 关闭质量权重，更稳定
                    autoclean=False,  # 手动控制清理
                    selected=False,
                    boundaryweight=2.0 if preserve_boundaries else 1.0  # 增加边界权重
                )
            except Exception as e:
                # 如果减面失败，直接跳出循环
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Step {step} failed: {e}\n")
                break
            
            current_faces = ms.current_mesh().face_number()
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Step {step} result: {current_faces} faces\n")
            
            step += 1
            
            # 严格的安全检查：
            # 1. 如果面数没有明显减少（少于5%），跳出循环
            if current_faces >= prev_faces * 0.95:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Breaking: insufficient reduction {current_faces}/{prev_faces}\n")
                break
            # 2. 如果面数异常（为0或负数），跳出循环
            if current_faces <= 0:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Breaking: abnormal face count {current_faces}\n")
                break
            # 3. 如果已经接近目标，跳出循环
            if current_faces <= target_faces * 1.05:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Breaking: close to target {current_faces}/{target_faces}\n")
                break
        
        # 最后一次精确简化到目标面数
        if current_faces > target_faces:
            try:
                ms.meshing_decimation_quadric_edge_collapse(
                    targetfacenum=target_faces,
                    preserveboundary=preserve_boundaries,
                    preservenormal=True,
                    preservetopology=True,
                    optimalplacement=True,
                    planarquadric=False,
                    qualityweight=False,
                    autoclean=True,
                    boundaryweight=2.0 if preserve_boundaries else 1.0
                )
            except Exception:
                # 如果最终简化失败，使用当前结果
                pass
    else:
        # 减面比例较小，直接一次性简化
        try:
            ms.meshing_decimation_quadric_edge_collapse(
                targetfacenum=target_faces,
                preserveboundary=preserve_boundaries,
                preservenormal=True,
                preservetopology=True,
                optimalplacement=True,
                planarquadric=False,
                qualityweight=False,
                autoclean=True,
                boundaryweight=2.0 if preserve_boundaries else 1.0
            )
        except Exception:
            # 如果简化失败，返回原始路径
            return input_path
    
    simplified_path = input_path.replace('.obj', '_simplified.obj')
    ms.save_current_mesh(simplified_path)
    
    return simplified_path

def high_quality_simplify(input_path: str, target_faces: int, preserve_boundaries: bool = True) -> str:
    """
    使用pymeshlab进行高质量减面，保持边缘清晰和网格完整性。
    现在使用渐进式简化避免模型破碎。
    Args:
        input_path (str): 输入OBJ文件路径
        target_faces (int): 目标面数
        preserve_boundaries (bool): 是否保持边界特征
    Returns:
        str: 简化后的OBJ文件路径
    """
    return progressive_simplify(input_path, target_faces, preserve_boundaries)

def safe_copy(src, dst_dir):
    import os, shutil
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src, dst)
    return dst

def simplify_with_uv_preservation(input_path: str, target_faces: int, preserve_boundaries: bool = True) -> str:
    """
    专门针对带贴图的模型进行减面，特别保护UV坐标。
    Args:
        input_path (str): 输入OBJ文件路径
        target_faces (int): 目标面数
        preserve_boundaries (bool): 是否保持边界特征
    Returns:
        str: 简化后的OBJ文件路径
    """
    ms = pymeshlab.MeshSet()
    try:
        ms.load_new_mesh(input_path)
    except Exception:
        # 如果加载失败，返回原始路径
        return input_path
    
    original_faces = ms.current_mesh().face_number()
    
    if original_faces <= target_faces:
        return input_path
    
    # 检查是否有UV坐标
    try:
        has_texcoords = ms.current_mesh().has_face_tex_coord() or ms.current_mesh().has_vert_tex_coord()
    except Exception:
        has_texcoords = False
    
    if has_texcoords:
        # 对有UV的模型使用更保守的参数
        reduction_ratio = target_faces / original_faces
        
        if reduction_ratio < 0.3:
            # 极大减面，需要非常保守
            intermediate_target = int(original_faces * 0.5)
            
            # 第一步：减少到50%
            try:
                ms.meshing_decimation_quadric_edge_collapse(
                    targetfacenum=intermediate_target,
                    preserveboundary=True,
                    preservenormal=True,
                    preservetopology=True,
                    optimalplacement=True,
                    planarquadric=False,
                    qualityweight=False,
                    autoclean=False,
                    boundaryweight=3.0,  # 增强边界保护
                    selected=False
                )
            except Exception:
                # 如果第一步失败，尝试更保守的参数
                try:
                    ms.meshing_decimation_quadric_edge_collapse(
                        targetfacenum=target_faces,
                        preserveboundary=True,
                        preservenormal=True,
                        preservetopology=False,  # 降低要求
                        optimalplacement=True,
                        planarquadric=False,
                        qualityweight=False,
                        autoclean=True,
                        boundaryweight=2.0,
                        selected=False
                    )
                except Exception:
                    # 如果仍然失败，返回原始路径
                    return input_path
            else:
                # 第二步：减少到目标面数
                try:
                    ms.meshing_decimation_quadric_edge_collapse(
                        targetfacenum=target_faces,
                        preserveboundary=True,
                        preservenormal=True,
                        preservetopology=True,
                        optimalplacement=True,
                        planarquadric=False,
                        qualityweight=False,
                        autoclean=True,
                        boundaryweight=3.0,
                        selected=False
                    )
                except Exception:
                    # 如果第二步失败，使用当前结果
                    pass
        else:
            # 中等减面，一次性完成
            try:
                ms.meshing_decimation_quadric_edge_collapse(
                    targetfacenum=target_faces,
                    preserveboundary=preserve_boundaries,
                    preservenormal=True,
                    preservetopology=True,
                    optimalplacement=True,
                    planarquadric=False,
                    qualityweight=False,
                    autoclean=True,
                    boundaryweight=2.0,
                    selected=False
                )
            except Exception:
                # 如果简化失败，返回原始路径
                return input_path
    else:
        # 没有UV坐标，使用标准简化
        return progressive_simplify(input_path, target_faces, preserve_boundaries)
    
    simplified_path = input_path.replace('.obj', '_uv_simplified.obj')
    try:
        ms.save_current_mesh(simplified_path)
    except Exception:
        # 如果保存失败，返回原始路径
        return input_path
    
    return simplified_path

def restore_obj_material(obj_path: str, original_obj_path: str):
    """
    将原始OBJ的mtl和贴图引用复制到新OBJ，修正mtllib和usemtl，保证贴图不丢失。
    同时在temp目录中查找相关文件。
    """
    if not os.path.exists(original_obj_path):
        return
        
    orig_dir = os.path.dirname(original_obj_path)
    new_dir = os.path.dirname(obj_path)
    
    try:
        with open(original_obj_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception:
        return
    
    mtl_files = [line.split()[1] for line in lines if line.lower().startswith('mtllib')]
    if not mtl_files:
        return
        
    mtl_file = mtl_files[0]
    # 处理可能的路径分隔符
    mtl_file = mtl_file.replace('\\', '/').split('/')[-1]
    
    # 先在原始目录查找，再在temp目录查找
    orig_mtl_path = os.path.join(orig_dir, mtl_file)
    temp_mtl_path = os.path.join(TEMP_DIR, mtl_file)
    
    mtl_source_path = None
    if os.path.exists(orig_mtl_path):
        mtl_source_path = orig_mtl_path
    elif os.path.exists(temp_mtl_path):
        mtl_source_path = temp_mtl_path
    
    if not mtl_source_path:
        return
        
    # 复制MTL文件
    try:
        safe_copy(mtl_source_path, new_dir)
    except Exception:
        return
    
    # 复制贴图文件
    try:
        with open(mtl_source_path, 'r', encoding='utf-8') as f:
            mtl_lines = f.readlines()
        
        for line in mtl_lines:
            line_lower = line.lower().strip()
            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal')):
                parts = line.split()
                if len(parts) > 1:
                    tex_file = parts[-1]  # 取最后一个部分作为文件名
                    # 处理可能的路径分隔符
                    tex_file = tex_file.replace('\\', '/').split('/')[-1]
                    
                    # 按优先级查找贴图文件：原始目录 -> temp目录
                    tex_source_path = None
                    orig_tex_path = os.path.join(orig_dir, tex_file)
                    temp_tex_path = os.path.join(TEMP_DIR, tex_file)
                    
                    if os.path.exists(orig_tex_path):
                        tex_source_path = orig_tex_path
                    elif os.path.exists(temp_tex_path):
                        tex_source_path = temp_tex_path
                    
                    if tex_source_path:
                        try:
                            safe_copy(tex_source_path, new_dir)
                        except Exception:
                            continue
    except Exception:
        pass
    
    # 修正新OBJ的mtllib引用
    try:
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
    except Exception:
        pass

def check_mesh_quality(obj_path: str) -> Dict[str, Any]:
    """
    检查网格质量，返回面数、边数、顶点数和拓扑信息。
    Args:
        obj_path (str): OBJ文件路径
    Returns:
        dict: 包含网格质量信息的字典
    """
    try:
        mesh = trimesh.load(obj_path, force='mesh')
        quality_info = {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.faces),
            "edges": len(mesh.edges),
            "watertight": mesh.is_watertight,
            "volume": mesh.volume if mesh.is_watertight else "N/A",
            "surface_area": mesh.area,
            "bounds": mesh.bounds.tolist(),
            "bbox_diagonal": ((mesh.bounds[1] - mesh.bounds[0]) ** 2).sum() ** 0.5
        }
        
        # 检查网格质量问题
        issues = []
        warnings = []
        
        if not mesh.is_watertight:
            issues.append("Not watertight (has holes)")
        if len(mesh.faces) == 0:
            issues.append("No faces")
        if len(mesh.vertices) == 0:
            issues.append("No vertices")
            
        # 检查是否可能破碎
        try:
            components = mesh.split(only_watertight=False)
            if len(components) > 1:
                warnings.append(f"Model has {len(components)} separate components")
                quality_info["components"] = len(components)
        except Exception:
            pass
        
        # 检查面积是否异常小（可能表示破碎）
        if mesh.area < 0.001:
            warnings.append("Very small surface area - model might be damaged")
            
        # 检查边长比例
        try:
            edge_lengths = mesh.edges_unique_length
            if len(edge_lengths) > 0:
                min_edge = edge_lengths.min()
                max_edge = edge_lengths.max()
                if max_edge > 0 and min_edge / max_edge < 0.001:
                    warnings.append("Extreme edge length variation - model might have artifacts")
        except Exception:
            pass
            
        quality_info["issues"] = issues
        quality_info["warnings"] = warnings
        return quality_info
    except Exception as e:
        return {"error": str(e)}

def create_model_archive(
    model_path: str, 
    original_input: str, 
    processing_info: Dict[str, Any],
    processing_log_file: str = None,
    temp_files: list = None
) -> str:
    """
    为处理后的模型创建归档文件夹，包含模型文件、材质、贴图和处理信息。
    Args:
        model_path (str): 输出模型文件路径
        original_input (str): 原始输入模型路径/URL
        processing_info (dict): 处理信息（面数、参数等）
        processing_log_file (str): 本次处理的日志文件路径
        temp_files (list): 临时文件列表，用于查找贴图文件
    Returns:
        str: 归档文件夹路径
    Raises:
        RuntimeError: 归档创建失败时抛出
    """
    try:
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        model_name = os.path.splitext(os.path.basename(model_path))[0]
        archive_name = f"{model_name}_{timestamp}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        
        # 记录开始信息到单独的归档日志
        archive_log = os.path.join(LOG_DIR, f"archive_{timestamp}.log")
        with open(archive_log, "w", encoding="utf-8") as logf:
            logf.write(f"Starting archive creation: {archive_name}\n")
            logf.write(f"Model path: {model_path}\n")
            logf.write(f"Archive path: {archive_path}\n")
        
        # 创建归档文件夹结构
        os.makedirs(archive_path, exist_ok=True)
        model_dir = os.path.join(archive_path, "model")
        textures_dir = os.path.join(archive_path, "textures")
        logs_dir = os.path.join(archive_path, "logs")
        
        os.makedirs(model_dir, exist_ok=True)
        os.makedirs(textures_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)
        
        with open(archive_log, "a", encoding="utf-8") as logf:
            logf.write("Directory structure created.\n")
        
        # 1. 复制主模型文件
        if os.path.exists(model_path):
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write(f"Copying main model file: {model_path}\n")
            shutil.copy2(model_path, model_dir)
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write("Main model file copied.\n")
        else:
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write(f"WARNING: Main model file not found: {model_path}\n")

        # 2. 从temp目录中查找并复制贴图文件
        texture_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tiff', '.dds', '.hdr', '.exr']
        copied_textures = []
        
        with open(archive_log, "a", encoding="utf-8") as logf:
            logf.write("Starting texture file search in temp directory...\n")
        
        # 在temp目录中查找贴图文件
        if os.path.exists(TEMP_DIR):
            temp_files_count = 0
            for file in os.listdir(TEMP_DIR):
                file_path = os.path.join(TEMP_DIR, file)
                if os.path.isfile(file_path):
                    temp_files_count += 1
                    _, ext = os.path.splitext(file.lower())
                    if ext in texture_extensions:
                        try:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Copying texture: {file}\n")
                            shutil.copy2(file_path, textures_dir)
                            copied_textures.append(file)
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Texture copied: {file}\n")
                        except Exception as e:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Failed to copy texture {file}: {e}\n")
                            continue
            
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write(f"Temp directory scan complete. Found {temp_files_count} files, copied {len(copied_textures)} textures.\n")
        else:
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write("Temp directory does not exist.\n")

        # 3. 查找并复制MTL文件和相关贴图
        if model_path.lower().endswith('.obj'):
            source_dir = os.path.dirname(model_path)
            model_base = os.path.splitext(os.path.basename(model_path))[0]
            
            # 查找MTL文件
            possible_mtl = os.path.join(source_dir, f"{model_base}.mtl")
            if os.path.exists(possible_mtl):
                shutil.copy2(possible_mtl, model_dir)
                
                # 从MTL文件中提取贴图文件引用
                try:
                    with open(possible_mtl, 'r', encoding='utf-8') as f:
                        for line in f:
                            line_lower = line.lower().strip()
                            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d')):
                                parts = line.split()
                                if len(parts) > 1:
                                    tex_file = parts[-1]
                                    # 先在模型目录查找
                                    tex_path = os.path.join(source_dir, tex_file)
                                    if os.path.exists(tex_path):
                                        shutil.copy2(tex_path, textures_dir)
                                        copied_textures.append(tex_file)
                                    # 再在temp目录查找
                                    else:
                                        temp_tex_path = os.path.join(TEMP_DIR, tex_file)
                                        if os.path.exists(temp_tex_path):
                                            shutil.copy2(temp_tex_path, textures_dir)
                                            copied_textures.append(tex_file)
                except Exception:
                    pass

        # 4. 创建处理信息文件
        info_data = {
            "archive_created": timestamp,
            "original_input": original_input,
            "output_model": os.path.basename(model_path),
            "processing_info": processing_info,
            "copied_textures": copied_textures,
            "file_structure": {
                "model/": "主模型文件和材质文件",
                "textures/": "从temp目录和模型目录复制的贴图文件",
                "logs/": "本次处理的日志文件",
                "info.json": "处理信息和元数据"
            }
        }
        
        info_json_path = os.path.join(archive_path, "info.json")
        with open(info_json_path, 'w', encoding='utf-8') as f:
            json.dump(info_data, f, indent=2, ensure_ascii=False)
        
        # 5. 复制本次处理的日志文件
        if processing_log_file and os.path.exists(processing_log_file):
            try:
                with open(archive_log, "a", encoding="utf-8") as logf:
                    logf.write(f"Copying processing log: {processing_log_file}\n")
                shutil.copy2(processing_log_file, logs_dir)
                log_filename = os.path.basename(processing_log_file)
                info_data["processing_log"] = log_filename
                # 更新info.json
                with open(info_json_path, 'w', encoding='utf-8') as f:
                    json.dump(info_data, f, indent=2, ensure_ascii=False)
                with open(archive_log, "a", encoding="utf-8") as logf:
                    logf.write("Processing log copied and info.json updated.\n")
            except Exception as e:
                with open(archive_log, "a", encoding="utf-8") as logf:
                    logf.write(f"Failed to copy processing log: {e}\n")
        
        with open(archive_log, "a", encoding="utf-8") as logf:
            logf.write("Archive creation completed successfully.\n")
        
        return archive_path
    
    except Exception as e:
        # 如果归档创建过程中出现任何错误，记录并抛出异常
        error_log = os.path.join(LOG_DIR, f"archive_error_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        with open(error_log, "w", encoding="utf-8") as logf:
            logf.write(f"Archive creation failed: {e}\n")
            logf.write(f"Model path: {model_path}\n")
            logf.write(f"Original input: {original_input}\n")
        raise RuntimeError(f"Failed to create archive: {e}")

def clean_old_archives(days_to_keep: int = 30) -> int:
    """
    清理旧的归档文件夹，保留指定天数内的文件夹。
    Args:
        days_to_keep (int): 保留的天数
    Returns:
        int: 删除的文件夹数量
    """
    if not os.path.exists(ARCHIVE_DIR):
        return 0
    
    cutoff_time = datetime.datetime.now() - datetime.timedelta(days=days_to_keep)
    deleted_count = 0
    
    for filename in os.listdir(ARCHIVE_DIR):
        file_path = os.path.join(ARCHIVE_DIR, filename)
        if os.path.isdir(file_path):
            try:
                file_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                if file_time < cutoff_time:
                    shutil.rmtree(file_path)
                    deleted_count += 1
            except Exception:
                continue
    
    return deleted_count

def clean_temp_directory() -> None:
    """
    彻底清空temp目录中的所有文件和子目录。
    """
    if not os.path.exists(TEMP_DIR):
        return
    
    try:
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception:
                continue
    except Exception:
        pass

def get_original_name(input_model: str) -> str:
    # 支持本地路径和URL
    if input_model.startswith('http://') or input_model.startswith('https://'):
        path = urllib.parse.urlparse(input_model).path
        return os.path.basename(path)
    else:
        return os.path.basename(input_model)

def validate_obj_package_internal(obj_file: str, mtl_files: list = None, texture_files: list = None) -> Dict[str, Any]:
    """
    内部使用的OBJ包验证函数
    """
    result = {
        "obj_file": {
            "path": obj_file,
            "exists": os.path.exists(obj_file),
            "valid": False
        },
        "referenced_mtl_files": [],
        "provided_mtl_files": [],
        "missing_mtl_files": [],
        "texture_files": [],
        "missing_textures": [],
        "warnings": [],
        "errors": []
    }
    
    if not os.path.exists(obj_file):
        result["errors"].append(f"OBJ file not found: {obj_file}")
        return result
    
    result["obj_file"]["valid"] = True
    
    # 检查OBJ文件中引用的MTL文件
    try:
        with open(obj_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.lower().startswith('mtllib'):
                    parts = line.split()
                    if len(parts) > 1:
                        referenced_mtl = parts[1].replace('\\', '/').split('/')[-1]
                        result["referenced_mtl_files"].append(referenced_mtl)
    except Exception as e:
        result["errors"].append(f"Failed to read OBJ file: {e}")
        return result
    
    # 检查MTL文件
    obj_dir = os.path.dirname(obj_file)
    for ref_mtl in result["referenced_mtl_files"]:
        if not os.path.exists(os.path.join(obj_dir, ref_mtl)):
            result["missing_mtl_files"].append(ref_mtl)
    
    return result

@mcp.tool()
async def process_model(
    input_model: str,
    additional_files: Optional[list] = None,
    target_faces: int = 5000,
    operation: str = "auto",
    mode: str = "balanced",
    preserve_boundaries: bool = True,
    preserve_uv: bool = True,
    options: Optional[Dict[str, Any]] = None,
    create_archive: bool = True
) -> str:
    """
    统一的模型处理工具，支持减面、重拓扑等操作。
    自动识别输入类型（单文件、文件夹、URL），智能选择最佳处理方式。

    Args:
        input_model (str): 输入模型路径（支持GLB/OBJ文件、文件夹或URL）
        additional_files (list): 额外的文件路径列表（MTL、贴图等，可选）
        target_faces (int): 目标面数
        operation (str): 操作类型
            - "auto": 自动选择（水密模型用simplify，有问题的用remesh）
            - "simplify": 纯减面，保持原有网格结构，保持边缘清晰
            - "remesh": 重拓扑，修复网格问题，生成新的拓扑结构
        mode (str): 处理模式（用于remesh操作）
            - "balanced": 平衡模式，适合大多数情况（默认）
            - "fine": 精细模式，生成更均匀的网格
            - "coarse": 粗糙模式，生成更少的面数
            - "fix_holes": 专门用于修复破洞的模式
        preserve_boundaries (bool): 是否保持边界特征
        preserve_uv (bool): 是否保持UV坐标
        options (dict): 其他Instant Meshes命令行参数（如{"-d": True, "-t": 4}）
        create_archive (bool): 是否创建归档文件夹
    Returns:
        str: 输出模型路径或归档文件夹路径（如果create_archive=True）
    Raises:
        RuntimeError: 处理失败时抛出
    """
    # 开始前先清理temp目录并设置日志
    clean_temp_directory()
    temp_files = []
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(LOG_DIR, f"process_model_{timestamp}.log")
    
    try:
        with open(log_file, "w", encoding="utf-8") as logf:
            logf.write(f"Starting model processing\n")
            logf.write(f"Input: {input_model}\n")
            logf.write(f"Target faces: {target_faces}\n")
            logf.write(f"Operation: {operation}\n")
            logf.write(f"Mode: {mode}\n")
            logf.write(f"Preserve UV: {preserve_uv}\n")
            logf.write(f"Create archive: {create_archive}\n")
            logf.write("Temp directory cleaned.\n")
        
        # 1. 处理输入模型（支持URL、多文件和文件夹）
        if os.path.isdir(input_model):
            # 文件夹模式：复制整个文件夹到temp
            obj_in = process_obj_with_materials(input_model, additional_files)
            temp_files.append(obj_in)
        elif input_model.lower().endswith(".obj"):
            # OBJ文件，使用新的处理函数
            obj_in = process_obj_with_materials(input_model, additional_files)
            temp_files.append(obj_in)
        elif is_url(input_model):
            local_input = download_to_temp(input_model)
            temp_files.append(local_input)
            
            # 2. 若输入为GLB，先转OBJ
            if local_input.lower().endswith(".glb"):
                obj_in = get_temp_file(".obj")
                glb_to_obj(local_input, obj_in)
                temp_files.append(obj_in)
            else:
                obj_in = local_input
        else:
            local_input = input_model
            
            # 2. 若输入为GLB，先转OBJ
            if local_input.lower().endswith(".glb"):
                obj_in = get_temp_file(".obj")
                glb_to_obj(local_input, obj_in)
                temp_files.append(obj_in)
            else:
                obj_in = local_input

        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Input processed: {obj_in}\n")

        # 2. 分析原始模型质量
        original_quality = check_mesh_quality(obj_in)
        original_faces = original_quality.get("faces", 0)
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Original faces: {original_faces}\n")
            logf.write(f"Original quality: {original_quality}\n")

        # 3. 智能选择操作方式
        if operation == "auto":
            # 根据模型质量自动选择处理方式
            is_watertight = original_quality.get("watertight", False)
            has_issues = len(original_quality.get("issues", [])) > 0
            
            if is_watertight and not has_issues:
                actual_operation = "simplify"
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write("Auto mode: Selected 'simplify' - model is watertight and has no issues\n")
            else:
                actual_operation = "remesh"
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Auto mode: Selected 'remesh' - watertight: {is_watertight}, issues: {original_quality.get('issues', [])}\n")
        else:
            actual_operation = operation

        # 4. 检查是否需要处理
        if original_faces <= target_faces:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write("Model already has fewer faces than target, no processing needed.\n")
            final_obj = obj_in
        else:
            # 5. 根据选择的操作进行处理
            if actual_operation == "simplify":
                # 纯减面模式
                try:
                    simplified_obj = simplify_with_uv_preservation(obj_in, target_faces, preserve_boundaries)
                    temp_files.append(simplified_obj)
                    final_obj = simplified_obj
                    
                    # 修复材质引用
                    restore_obj_material(final_obj, obj_in)
                    
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write("Simplify operation completed successfully.\n")
                        
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"ERROR: Simplify operation failed: {e}\n")
                    raise RuntimeError(f"Simplify operation failed: {e}")
            else:
                # 重拓扑模式
                try:
                    repaired_obj = repair_mesh_with_pymeshlab(obj_in)
                    temp_files.append(repaired_obj)
                    obj_in = repaired_obj
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"WARNING: Mesh repair failed: {e}\n")

                # 输出先到临时文件
                temp_output = get_temp_file(".obj")
                temp_files.append(temp_output)

                # Instant Meshes重拓扑
                run_instant_meshes(obj_in, temp_output, target_faces, extra_options=options, mode=mode)
                restore_obj_material(temp_output, obj_in)
                final_obj = temp_output

        # 6. 检查处理结果质量
        final_quality = check_mesh_quality(final_obj)
        final_faces = final_quality.get('faces', 0)
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Final faces: {final_faces}\n")
            logf.write(f"Reduction ratio: {final_faces/original_faces:.2%}\n")
            logf.write(f"Final quality: {final_quality}\n")

        # 7. 输出为GLB
        temp_glb = get_temp_file(".glb")
        obj_to_glb(final_obj, temp_glb)
        temp_files.append(temp_glb)

        # 8. 移动到输出目录
        orig_name = get_original_name(input_model)
        output_name = os.path.splitext(orig_name)[0] + f"_{actual_operation}.glb"
        output_model = os.path.join(OUTPUT_DIR, output_name)
        move_and_cleanup(temp_glb, output_model)
        
        # 9. 创建归档（可选）
        if create_archive:
            processing_info = {
                "operation": actual_operation,
                "mode": mode,
                "original_faces": original_faces,
                "target_faces": target_faces,
                "final_faces": final_faces,
                "reduction_ratio": f"{final_faces/original_faces:.2%}",
                "preserve_boundaries": preserve_boundaries,
                "preserve_uv": preserve_uv,
                "options": options,
                "quality_info": final_quality
            }
            
            archive_path = create_model_archive(
                output_model, 
                input_model, 
                processing_info, 
                processing_log_file=log_file,
                temp_files=temp_files
            )
            
            return archive_path
        else:
            return output_model
    finally:
        # 清理所有临时文件
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        
        # 彻底清空temp目录
        clean_temp_directory()

@mcp.tool()
async def analyze_model(
    input_path: str,
    analysis_type: str = "auto",
    include_folder_analysis: bool = False,
    include_validation: bool = False
) -> Dict[str, Any]:
    """
    统一的模型分析工具，支持网格质量分析、文件夹分析、包完整性验证等。
    
    Args:
        input_path (str): 输入路径（模型文件、文件夹或URL）
        analysis_type (str): 分析类型
            - "auto": 自动检测输入类型并选择合适的分析方式
            - "quality": 仅分析网格质量
            - "folder": 仅分析OBJ文件夹结构
            - "validation": 仅验证OBJ包完整性
            - "full": 执行所有可用的分析
        include_folder_analysis (bool): 如果输入是单个OBJ文件，是否同时分析其所在文件夹
        include_validation (bool): 如果输入是OBJ文件，是否同时验证包完整性
    Returns:
        dict: 包含分析结果的字典
    Raises:
        RuntimeError: 分析失败时抛出
    """
    try:
        result = {
            "input_path": input_path,
            "analysis_timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "analyses_performed": []
        }
        
        # 自动检测输入类型
        is_folder = os.path.isdir(input_path)
        is_obj_file = input_path.lower().endswith('.obj') and os.path.isfile(input_path)
        is_model_file = (input_path.lower().endswith(('.obj', '.glb')) and os.path.isfile(input_path)) or is_url(input_path)
        
        # 决定要执行的分析
        if analysis_type == "auto":
            if is_folder:
                analyses_to_run = ["folder", "quality"]
            elif is_obj_file:
                analyses_to_run = ["quality", "validation"]
                if include_folder_analysis:
                    analyses_to_run.append("folder")
            elif is_model_file:
                analyses_to_run = ["quality"]
            else:
                raise RuntimeError(f"Unsupported input type: {input_path}")
        elif analysis_type == "full":
            if is_folder:
                analyses_to_run = ["folder", "quality"]
            elif is_obj_file:
                analyses_to_run = ["quality", "validation", "folder"]
            elif is_model_file:
                analyses_to_run = ["quality"]
            else:
                raise RuntimeError(f"Unsupported input type for full analysis: {input_path}")
        else:
            analyses_to_run = [analysis_type]
        
        # 执行分析
        for analysis in analyses_to_run:
            try:
                if analysis == "quality":
                    # 网格质量分析
                    if is_folder:
                        # 文件夹模式：分析第一个OBJ文件
                        folder_analysis = analyze_obj_folder(input_path)
                        if folder_analysis.get("obj_files"):
                            first_obj = os.path.join(input_path, folder_analysis["obj_files"][0])
                            quality_result = check_mesh_quality(first_obj)
                        else:
                            quality_result = {"error": "No OBJ files found in folder"}
                    else:
                        # 处理GLB文件
                        if input_path.lower().endswith('.glb') or (is_url(input_path) and 'glb' in input_path.lower()):
                            temp_obj = get_temp_file('.obj')
                            if is_url(input_path):
                                local_file = download_to_temp(input_path)
                                glb_to_obj(local_file, temp_obj)
                                os.remove(local_file)
                            else:
                                glb_to_obj(input_path, temp_obj)
                            
                            quality_result = check_mesh_quality(temp_obj)
                            os.remove(temp_obj)
                        else:
                            # 处理OBJ文件或URL
                            if is_url(input_path):
                                local_file = download_to_temp(input_path)
                                quality_result = check_mesh_quality(local_file)
                                os.remove(local_file)
                            else:
                                quality_result = check_mesh_quality(input_path)
                    
                    # 添加推荐建议
                    if "faces" in quality_result:
                        current_faces = quality_result["faces"]
                        quality_result.update({
                            "recommended_target_faces": current_faces // 5 if current_faces > 5000 else current_faces,
                            "complexity_level": "high" if current_faces > 20000 else "medium" if current_faces > 5000 else "low",
                            "recommended_operation": "simplify" if quality_result.get("watertight", False) else "remesh",
                            "reduction_suggestions": {
                                "aggressive": current_faces // 10,
                                "moderate": current_faces // 5,
                                "conservative": current_faces // 2
                            }
                        })
                    
                    result["mesh_quality"] = quality_result
                    result["analyses_performed"].append("quality")
                
                elif analysis == "folder":
                    # 文件夹结构分析
                    if is_folder:
                        folder_result = analyze_obj_folder(input_path)
                    elif is_obj_file:
                        # 分析OBJ文件所在的文件夹
                        folder_path = os.path.dirname(input_path)
                        folder_result = analyze_obj_folder(folder_path)
                        folder_result["note"] = f"Analysis of folder containing {os.path.basename(input_path)}"
                    else:
                        folder_result = {"error": "Folder analysis not applicable for this input type"}
                    
                    result["folder_analysis"] = folder_result
                    result["analyses_performed"].append("folder")
                
                elif analysis == "validation":
                    # OBJ包完整性验证
                    if is_obj_file:
                        validation_result = validate_obj_package_internal(input_path)
                    elif is_folder:
                        # 验证文件夹中的主OBJ文件
                        folder_analysis = analyze_obj_folder(input_path)
                        if folder_analysis.get("obj_files"):
                            main_obj = os.path.join(input_path, folder_analysis["obj_files"][0])
                            validation_result = validate_obj_package_internal(main_obj)
                            validation_result["note"] = f"Validation of main OBJ file: {folder_analysis['obj_files'][0]}"
                        else:
                            validation_result = {"error": "No OBJ files found for validation"}
                    else:
                        validation_result = {"error": "Package validation only applicable for OBJ files"}
                    
                    result["package_validation"] = validation_result
                    result["analyses_performed"].append("validation")
                    
            except Exception as e:
                result[f"{analysis}_error"] = str(e)

        # 清空temp目录
        clean_temp_directory()
        
        return result
        
    except Exception as e:
        clean_temp_directory()
        raise RuntimeError(f"Failed to analyze model: {e}")



@mcp.tool()
async def manage_archives(
    action: str,
    archive_name: str = None,
    limit: int = 20,
    days_to_keep: int = 30,
    dry_run: bool = True,
    copy_to: str = None
) -> Dict[str, Any]:
    """
    统一的归档管理工具，支持列出、清理、复制归档等操作。
    
    Args:
        action (str): 操作类型
            - "list": 列出归档文件夹
            - "clean": 清理旧的归档文件夹
            - "copy": 复制指定的归档文件夹
            - "info": 获取归档目录的详细信息
        archive_name (str): 归档名称（用于copy操作）
        limit (int): 列出归档的数量限制（用于list操作）
        days_to_keep (int): 清理时保留的天数（用于clean操作）
        dry_run (bool): 是否只是预览而不实际删除（用于clean操作）
        copy_to (str): 复制到的目录路径（用于copy操作，可选）
    Returns:
        dict: 操作结果
    Raises:
        RuntimeError: 操作失败时抛出
    """
    try:
        if action == "list":
            # 列出归档
            if not os.path.exists(ARCHIVE_DIR):
                return {"action": "list", "archives": [], "total_count": 0, "total_size": 0}
            
            archives = []
            total_size = 0
            
            # 获取所有归档文件夹
            archive_dirs = []
            for filename in os.listdir(ARCHIVE_DIR):
                file_path = os.path.join(ARCHIVE_DIR, filename)
                if os.path.isdir(file_path):
                    archive_dirs.append((filename, file_path))
            
            # 按修改时间排序
            archive_dirs.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
            
            # 处理前limit个文件夹
            for filename, dir_path in archive_dirs[:limit]:
                try:
                    # 计算文件夹大小
                    dir_size = 0
                    for dirpath, dirnames, filenames in os.walk(dir_path):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            if os.path.exists(fp):
                                dir_size += os.path.getsize(fp)
                    
                    dir_time = datetime.datetime.fromtimestamp(os.path.getmtime(dir_path))
                    total_size += dir_size
                    
                    # 尝试读取info.json
                    info = {}
                    info_path = os.path.join(dir_path, 'info.json')
                    if os.path.exists(info_path):
                        try:
                            with open(info_path, 'r', encoding='utf-8') as f:
                                info = json.load(f)
                        except Exception:
                            pass
                    
                    archives.append({
                        "dirname": filename,
                        "size": dir_size,
                        "size_mb": round(dir_size / (1024 * 1024), 2),
                        "created": dir_time.strftime('%Y-%m-%d %H:%M:%S'),
                        "processing_info": info.get("processing_info", {}),
                        "original_input": info.get("original_input", "Unknown")
                    })
                    
                except Exception:
                    continue
            
            return {
                "action": "list",
                "archives": archives,
                "total_count": len(archive_dirs),
                "total_size": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "archive_directory": ARCHIVE_DIR
            }

        elif action == "clean":
            # 清理归档
            if not os.path.exists(ARCHIVE_DIR):
                return {"action": "clean", "deleted_count": 0, "freed_space": 0, "message": "Archive directory not found"}
            
            cutoff_time = datetime.datetime.now() - datetime.timedelta(days=days_to_keep)
            dirs_to_delete = []
            total_size = 0
            
            # 找出要删除的文件夹
            for filename in os.listdir(ARCHIVE_DIR):
                dir_path = os.path.join(ARCHIVE_DIR, filename)
                if os.path.isdir(dir_path):
                    try:
                        dir_time = datetime.datetime.fromtimestamp(os.path.getmtime(dir_path))
                        if dir_time < cutoff_time:
                            # 计算文件夹大小
                            dir_size = 0
                            for dirpath, dirnames, filenames in os.walk(dir_path):
                                for f in filenames:
                                    fp = os.path.join(dirpath, f)
                                    if os.path.exists(fp):
                                        dir_size += os.path.getsize(fp)
                            
                            dirs_to_delete.append({
                                "dirname": filename,
                                "size": dir_size,
                                "created": dir_time.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            total_size += dir_size
                    except Exception:
                        continue
            
            deleted_count = 0
            if not dry_run:
                # 实际删除文件夹
                for dir_info in dirs_to_delete:
                    try:
                        dir_path = os.path.join(ARCHIVE_DIR, dir_info["dirname"])
                        shutil.rmtree(dir_path)
                        deleted_count += 1
                    except Exception:
                        continue
            
            return {
                "action": "clean",
                "dirs_to_delete" if dry_run else "deleted_dirs": dirs_to_delete,
                "deleted_count": deleted_count if not dry_run else len(dirs_to_delete),
                "freed_space": total_size,
                "freed_space_mb": round(total_size / (1024 * 1024), 2),
                "dry_run": dry_run,
                "cutoff_date": cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
            }

        elif action == "copy":
            # 复制归档
            if not archive_name:
                raise RuntimeError("Archive name is required for copy operation")
            
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)
            if not os.path.exists(archive_path):
                raise RuntimeError(f"Archive not found: {archive_name}")
            
            if not os.path.isdir(archive_path):
                raise RuntimeError(f"Archive is not a directory: {archive_name}")
            
            if copy_to is None:
                copy_to = os.path.join(OUTPUT_DIR, "extracted", archive_name)
            
            if os.path.exists(copy_to):
                shutil.rmtree(copy_to)
            shutil.copytree(archive_path, copy_to)
            
            return {
                "action": "copy",
                "archive_name": archive_name,
                "copied_to": copy_to,
                "success": True
            }
        
        elif action == "info":
            # 获取归档目录信息
            if not os.path.exists(ARCHIVE_DIR):
                return {"action": "info", "exists": False}
            
            total_archives = 0
            total_size = 0
            oldest_date = None
            newest_date = None
            
            for filename in os.listdir(ARCHIVE_DIR):
                dir_path = os.path.join(ARCHIVE_DIR, filename)
                if os.path.isdir(dir_path):
                    total_archives += 1
                    
                    # 计算大小
                    for dirpath, dirnames, filenames in os.walk(dir_path):
                        for f in filenames:
                            fp = os.path.join(dirpath, f)
                            if os.path.exists(fp):
                                total_size += os.path.getsize(fp)
                    
                    # 检查日期
                    dir_time = datetime.datetime.fromtimestamp(os.path.getmtime(dir_path))
                    if oldest_date is None or dir_time < oldest_date:
                        oldest_date = dir_time
                    if newest_date is None or dir_time > newest_date:
                        newest_date = dir_time
            
            return {
                "action": "info",
                "exists": True,
                "archive_directory": ARCHIVE_DIR,
                "total_archives": total_archives,
                "total_size": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "oldest_archive": oldest_date.strftime('%Y-%m-%d %H:%M:%S') if oldest_date else None,
                "newest_archive": newest_date.strftime('%Y-%m-%d %H:%M:%S') if newest_date else None
            }
        
        else:
            raise RuntimeError(f"Unsupported action: {action}. Use 'list', 'clean', 'copy', or 'info'")
            
    except Exception as e:
        raise RuntimeError(f"Archive management failed: {e}")



if __name__ == "__main__":
    mcp.run(transport='stdio')