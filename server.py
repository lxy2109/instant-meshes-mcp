"""
Instant Meshes MCP Server

This server provides tools for 3D model processing using Instant Meshes and pymeshlab.
It supports mesh simplification, remeshing, and quality analysis.

Blender 3.6 Integration:
The server automatically detects Blender 3.6 installations for GLB/OBJ conversion.
Detection priority:
1. BLENDER_EXECUTABLE environment variable (highest priority)
2. BLENDER_PATH environment variable (compatibility)
3. Automatic system detection (Windows/macOS/Linux)
4. PATH environment variable search

To specify a custom Blender path, set the environment variable:
Windows: set BLENDER_EXECUTABLE=C:\Path\To\blender.exe
Linux/macOS: export BLENDER_EXECUTABLE=/path/to/blender

Use test_blender_detection_tool() to diagnose detection issues.
"""

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
import platform

mcp = FastMCP("instant_meshes")

def find_blender_executable() -> Optional[str]:
    """
    自动检索设备中的Blender 3.6可执行文件。
    支持Windows、macOS和Linux系统，检查多个常见安装位置。
    Returns:
        str: Blender 3.6可执行文件路径，如果未找到则返回None
    """
    system = platform.system().lower()
    
    # 定义不同系统的可能路径
    if system == "windows":
        # Windows系统的可能路径
        possible_paths = [
            # 用户自定义路径（从环境变量或注册表）
            os.environ.get("BLENDER_PATH"),
            
            # 标准安装路径
            r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
            r"C:\Program Files (x86)\Blender Foundation\Blender 3.6\blender.exe",
            
            # 其他常见驱动器
            r"D:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
            r"E:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
            r"F:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
            
            # 便携版路径
            r"C:\Blender\3.6\blender.exe",
            r"D:\Blender\3.6\blender.exe",
            r"E:\Blender\3.6\blender.exe",
            r"H:\Blender\3.6\blender.exe",  # 用户原有路径
            
            # Steam安装路径
            r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
            r"C:\Program Files\Steam\steamapps\common\Blender\blender.exe",
            
            # 用户目录安装
            os.path.expanduser(r"~\AppData\Local\Programs\Blender Foundation\Blender 3.6\blender.exe"),
            os.path.expanduser(r"~\Documents\Blender\3.6\blender.exe"),
            
            # 当前目录相对路径
            r".\blender\blender.exe",
            r".\Blender 3.6\blender.exe",
        ]
        
        # 尝试从PATH环境变量中查找
        path_env = os.environ.get("PATH", "")
        for path_dir in path_env.split(os.pathsep):
            if "blender" in path_dir.lower():
                blender_exe = os.path.join(path_dir, "blender.exe")
                if os.path.exists(blender_exe):
                    possible_paths.append(blender_exe)
        
        # 尝试从注册表查找（Windows特有）
        try:
            import winreg
            # 查找Blender在注册表中的安装路径
            registry_paths = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Blender Foundation\Blender\3.6"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Blender Foundation\Blender\3.6"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Blender Foundation\Blender\3.6"),
            ]
            
            for hkey, subkey in registry_paths:
                try:
                    with winreg.OpenKey(hkey, subkey) as key:
                        install_path = winreg.QueryValueEx(key, "InstallDir")[0]
                        blender_exe = os.path.join(install_path, "blender.exe")
                        if os.path.exists(blender_exe):
                            possible_paths.append(blender_exe)
                except (FileNotFoundError, OSError):
                    continue
        except ImportError:
            pass  # winreg不可用（非Windows系统）
            
    elif system == "darwin":  # macOS
        possible_paths = [
            # 标准应用程序路径
            "/Applications/Blender.app/Contents/MacOS/Blender",
            "/Applications/Blender 3.6/Blender.app/Contents/MacOS/Blender",
            
            # 用户应用程序路径
            os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
            os.path.expanduser("~/Applications/Blender 3.6/Blender.app/Contents/MacOS/Blender"),
            
            # Homebrew路径
            "/usr/local/bin/blender",
            "/opt/homebrew/bin/blender",
            
            # MacPorts路径
            "/opt/local/bin/blender",
            
            # 其他可能路径
            "/usr/bin/blender",
            "/usr/local/Cellar/blender/*/bin/blender",
        ]
        
    else:  # Linux和其他Unix系统
        possible_paths = [
            # 标准系统路径
            "/usr/bin/blender",
            "/usr/local/bin/blender",
            "/opt/blender/blender",
            "/opt/blender-3.6/blender",
            
            # Snap包路径
            "/snap/blender/current/blender",
            
            # Flatpak路径
            "/var/lib/flatpak/app/org.blender.Blender/current/active/files/blender",
            os.path.expanduser("~/.local/share/flatpak/app/org.blender.Blender/current/active/files/blender"),
            
            # AppImage路径
            os.path.expanduser("~/Applications/Blender-3.6-linux-x64.AppImage"),
            os.path.expanduser("~/Downloads/Blender-3.6-linux-x64.AppImage"),
            
            # 用户本地安装
            os.path.expanduser("~/blender/blender"),
            os.path.expanduser("~/blender-3.6/blender"),
            os.path.expanduser("~/.local/bin/blender"),
            
            # 其他常见路径
            "/home/blender/blender",
            "/opt/blender-foundation/blender-3.6/blender",
        ]
        
        # 从PATH环境变量查找
        import shutil
        path_blender = shutil.which("blender")
        if path_blender:
            possible_paths.insert(0, path_blender)
    
    # 移除None值和重复路径
    possible_paths = list(dict.fromkeys([p for p in possible_paths if p is not None]))
    
    # 逐一检查路径
    for path in possible_paths:
        try:
            # 展开通配符路径（如/usr/local/Cellar/blender/*/bin/blender）
            if '*' in path:
                import glob
                expanded_paths = glob.glob(path)
                for expanded_path in expanded_paths:
                    if os.path.exists(expanded_path) and os.access(expanded_path, os.X_OK):
                        # 验证版本
                        if verify_blender_version(expanded_path):
                            return expanded_path
            else:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    # 验证版本
                    if verify_blender_version(path):
                        return path
        except Exception:
            continue
    
    return None

def verify_blender_version(blender_path: str, required_version: str = "3.6") -> bool:
    """
    验证Blender可执行文件的版本。
    Args:
        blender_path (str): Blender可执行文件路径
        required_version (str): 要求的版本号
    Returns:
        bool: 是否为要求的版本
    """
    try:
        result = subprocess.run(
            [blender_path, "--version"], 
            capture_output=True, 
            text=True, 
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )
        
        if result.returncode == 0:
            version_output = result.stdout.lower()
            # 检查版本号（支持3.6.x格式）
            if required_version in version_output or f"blender {required_version}" in version_output:
                return True
            
            # 更精确的版本检查
            import re
            version_pattern = r"blender\s+(\d+\.\d+)"
            match = re.search(version_pattern, version_output)
            if match:
                found_version = match.group(1)
                return found_version.startswith(required_version)
                
        return False
    except Exception:
        return False

def get_blender_executable_with_fallback() -> Optional[str]:
    """
    获取Blender可执行文件路径，包含回退机制。
    支持以下检测方式（按优先级）：
    1. BLENDER_EXECUTABLE 环境变量
    2. BLENDER_PATH 环境变量
    3. 自动检测系统中的Blender 3.6
    4. 通用命令检测
    
    Returns:
        str: Blender可执行文件路径，如果未找到则返回None
    """
    # 1. 优先检查 BLENDER_EXECUTABLE 环境变量
    blender_env = os.environ.get("BLENDER_EXECUTABLE")
    if blender_env and os.path.exists(blender_env) and verify_blender_version(blender_env):
        return blender_env
    
    # 2. 检查 BLENDER_PATH 环境变量（兼容性）
    blender_path_env = os.environ.get("BLENDER_PATH")
    if blender_path_env and os.path.exists(blender_path_env) and verify_blender_version(blender_path_env):
        return blender_path_env
    
    # 3. 尝试自动检测
    blender_exe = find_blender_executable()
    
    if blender_exe:
        return blender_exe
    
    # 4. 如果自动检测失败，尝试一些通用命令
    fallback_commands = ["blender", "blender3.6", "blender-3.6"]
    
    for cmd in fallback_commands:
        try:
            import shutil
            path = shutil.which(cmd)
            if path and verify_blender_version(path):
                return path
        except Exception:
            continue
    
    return None

def test_blender_detection() -> Dict[str, Any]:
    """
    测试Blender检测功能，返回详细的检测结果。
    Returns:
        Dict[str, Any]: 包含检测结果的字典
    """
    result = {
        "system": platform.system(),
        "architecture": platform.architecture(),
        "environment_variables": {
            "BLENDER_EXECUTABLE": os.environ.get("BLENDER_EXECUTABLE"),
            "BLENDER_PATH": os.environ.get("BLENDER_PATH"),
            "PATH": os.environ.get("PATH", "").split(os.pathsep)[:5]  # 只显示前5个PATH条目
        },
        "detection_results": {},
        "final_result": None,
        "error": None
    }
    
    try:
        # 测试环境变量检测
        blender_env = os.environ.get("BLENDER_EXECUTABLE")
        if blender_env:
            result["detection_results"]["env_BLENDER_EXECUTABLE"] = {
                "path": blender_env,
                "exists": os.path.exists(blender_env),
                "version_valid": verify_blender_version(blender_env) if os.path.exists(blender_env) else False
            }
        
        blender_path_env = os.environ.get("BLENDER_PATH")
        if blender_path_env:
            result["detection_results"]["env_BLENDER_PATH"] = {
                "path": blender_path_env,
                "exists": os.path.exists(blender_path_env),
                "version_valid": verify_blender_version(blender_path_env) if os.path.exists(blender_path_env) else False
            }
        
        # 测试自动检测
        auto_detected = find_blender_executable()
        if auto_detected:
            result["detection_results"]["auto_detection"] = {
                "path": auto_detected,
                "exists": os.path.exists(auto_detected),
                "version_valid": verify_blender_version(auto_detected)
            }
        
        # 测试通用命令
        fallback_commands = ["blender", "blender3.6", "blender-3.6"]
        for cmd in fallback_commands:
            try:
                import shutil
                path = shutil.which(cmd)
                if path:
                    result["detection_results"][f"command_{cmd}"] = {
                        "path": path,
                        "exists": os.path.exists(path),
                        "version_valid": verify_blender_version(path)
                    }
            except Exception as e:
                result["detection_results"][f"command_{cmd}"] = {
                    "error": str(e)
                }
        
        # 获取最终结果
        final_blender = get_blender_executable_with_fallback()
        result["final_result"] = {
            "path": final_blender,
            "success": final_blender is not None
        }
        
        if final_blender:
            # 获取版本信息
            try:
                version_result = subprocess.run(
                    [final_blender, "--version"], 
                    capture_output=True, 
                    text=True, 
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
                )
                if version_result.returncode == 0:
                    result["final_result"]["version_output"] = version_result.stdout.strip()
            except Exception as e:
                result["final_result"]["version_error"] = str(e)
        
    except Exception as e:
        result["error"] = str(e)
    
    return result

def run_blender_with_start(blender_exe: str, script_path: str, done_flag_path: str, timeout: int = 120) -> bool:
    """
    使用Windows start命令启动Blender，确保独立运行。
    Args:
        blender_exe (str): Blender可执行文件路径
        script_path (str): Blender脚本文件路径
        done_flag_path (str): 完成标记文件路径
        timeout (int): 超时时间（秒）
    Returns:
        bool: 是否成功完成
    """
    try:
        # 构建命令
        if platform.system() == "Windows":
            # Windows使用start命令独立启动
            cmd = f'start "" "{blender_exe}" --background --python "{script_path}"'
        else:
            # Unix系统使用nohup或直接启动
            cmd = f'nohup "{blender_exe}" --background --python "{script_path}" > /dev/null 2>&1 &'
        
        # 启动Blender进程
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待完成标记文件
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(done_flag_path):
                return True
            time.sleep(1)
        
        return False
        
    except Exception as e:
        print(f"Failed to run Blender: {e}")
        return False

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
    import time
    
    parsed = urllib.parse.urlparse(url)
    base = os.path.basename(parsed.path)  # 只取路径部分
    suffix = os.path.splitext(base)[-1] if '.' in base else ''
    temp_path = get_temp_file(suffix)
    
    # 设置请求头，模拟常见浏览器请求
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    # 添加重试机制
    max_retries = 3
    retry_delay = 2  # 秒
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, headers=headers, timeout=30)
            response.raise_for_status()
            
            with open(temp_path, 'wb') as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk)
            return temp_path
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                error_msg = f"Access forbidden (403) for URL: {url}"
                if attempt < max_retries - 1:
                    error_msg += f" - Retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})"
                    time.sleep(retry_delay)
                    retry_delay *= 1.5  # 指数退避
                    continue
                else:
                    # 提供详细的403错误信息和建议
                    detailed_error = f"""
Access Forbidden (403) Error for URL: {url}

This error typically occurs when:
1. The download link has expired (common with AI-generated model services)
2. The resource requires authentication or special permissions
3. The URL is private or has been revoked
4. Rate limiting is in effect

Suggested solutions:
1. Check if you have a fresh/valid download link
2. For Meshy AI models: Try regenerating the download link from your dashboard
3. For private repositories: Ensure you have proper access credentials
4. Download the file manually and use a local path instead

If this is a Meshy AI URL, the download link may have expired. Please:
- Log into your Meshy AI account
- Navigate to your model
- Generate a new download link
- Use the fresh URL or download the file locally
"""
                    raise RuntimeError(detailed_error)
            elif e.response.status_code == 404:
                raise RuntimeError(f"File not found (404) for URL: {url}. The resource may have been moved or deleted.")
            elif e.response.status_code in [429, 503]:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    raise RuntimeError(f"Service temporarily unavailable ({e.response.status_code}) for URL: {url}")
            else:
                raise RuntimeError(f"HTTP error {e.response.status_code} for URL: {url}")
                
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise RuntimeError(f"Download timeout for URL: {url}")
                
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise RuntimeError(f"Connection error for URL: {url}")
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                raise RuntimeError(f"Failed to download from URL {url}: {e}")
    
    # 如果所有重试都失败，抛出最终错误
    raise RuntimeError(f"Failed to download after {max_retries} attempts: {url}")

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
                    if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal', 'map_normalgl', 'map_orm', 'map_roughness', 'map_metallic', 'map_ao', 'map_emissive', 'map_opacity', 'map_displacement', 'map_height')):
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
                                        if mtl_line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal', 'map_normalgl', 'map_orm', 'map_roughness', 'map_metallic', 'map_ao', 'map_emissive', 'map_opacity', 'map_displacement', 'map_height')):
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
    
    # 智能识别并复制可能的贴图文件（基于命名约定）
    try:
        for filename in os.listdir(obj_dir):
            file_path = os.path.join(obj_dir, filename)
            if os.path.isfile(file_path) and is_texture_file(filename):
                temp_tex_path = os.path.join(TEMP_DIR, filename)
                if not os.path.exists(temp_tex_path):  # 避免重复复制
                    try:
                        shutil.copy2(file_path, temp_tex_path)
                    except Exception:
                        continue
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
    texture_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tiff', '.dds', '.hdr', '.exr', '.webp', '.ktx', '.ktx2', '.basis']
    
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path):
            lower_name = filename.lower()
            if lower_name.endswith('.obj'):
                result["obj_files"].append(filename)
            elif lower_name.endswith('.mtl'):
                result["mtl_files"].append(filename)
            elif is_texture_file(filename):
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
                            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal', 'map_normalgl', 'map_orm', 'map_roughness', 'map_metallic', 'map_ao', 'map_emissive', 'map_opacity', 'map_displacement', 'map_height')):
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

def glb_to_obj_with_textures(glb_path: str, obj_path: str) -> list:
    """
    将GLB转换为OBJ，并提取所有嵌入的贴图文件。
    优先使用Blender以更好地处理材质和贴图，如果Blender不可用则使用trimesh。
    Args:
        glb_path (str): 输入GLB文件路径
        obj_path (str): 输出OBJ文件路径
    Returns:
        list: 提取的贴图文件路径列表
    Raises:
        RuntimeError: 转换失败时抛出
    """
    import trimesh
    import time
    
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(LOG_DIR, f"glb_to_obj_{timestamp}.log")
    extracted_textures = []
    
    with open(log_file, "w", encoding="utf-8") as logf:
        logf.write(f"Starting GLB to OBJ conversion with texture extraction\n")
        logf.write(f"Input GLB: {glb_path}\n")
        logf.write(f"Output OBJ: {obj_path}\n")
        logf.write(f"File exists: {os.path.exists(glb_path)}\n")
        if os.path.exists(glb_path):
            logf.write(f"File size: {os.path.getsize(glb_path)} bytes\n")
    
    # 首先尝试使用Blender进行转换和贴图提取
    try:
        # 自动检测Blender 3.6可执行文件
        blender_exe = get_blender_executable_with_fallback()
        
        # 记录检测结果
        with open(log_file, "a", encoding="utf-8") as logf:
            if blender_exe:
                logf.write(f"Blender 3.6 detected at: {blender_exe}\n")
            else:
                logf.write("Blender 3.6 not found, will use fallback method\n")
        
        if blender_exe:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Using Blender: {blender_exe}\n")
            
            # 创建完成标记文件路径（确保是唯一的）
            done_flag_path = get_temp_file(".done")
            
            # 确保完成标记文件不存在（清理之前可能残留的文件）
            if os.path.exists(done_flag_path):
                try:
                    os.remove(done_flag_path)
                except Exception:
                    pass
            
            # 创建Blender调试日志文件
            blender_debug_log = os.path.join(LOG_DIR, "blender_debug.log")
            
            # 在日志文件中插入分隔标记
            with open(blender_debug_log, "a", encoding="utf-8") as debug_logf:
                debug_logf.write(f"\n===== {timestamp} Blender GLB to OBJ with Texture Extraction =====\n")
                debug_logf.write(f"Input GLB: {glb_path}\n")
                debug_logf.write(f"Output OBJ: {obj_path}\n")
                debug_logf.write(f"Blender executable: {blender_exe}\n")
                debug_logf.write(f"Done flag path: {done_flag_path}\n")
            
            # 创建输出目录
            output_dir = os.path.dirname(obj_path)
            os.makedirs(output_dir, exist_ok=True)
            
            # 创建Blender脚本，增强贴图提取功能
            script_content = f'''
import bpy
import os
import sys
import time
import shutil

# 重定向输出到调试日志文件
debug_log_path = r"{blender_debug_log}"
done_flag_path = r"{done_flag_path}"
obj_output_path = r"{obj_path}"
output_dir = r"{output_dir}"

def log_message(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(debug_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{{timestamp}}] {{message}}\\n")

def write_done_flag():
    try:
        with open(done_flag_path, "w", encoding="utf-8") as f:
            f.write("completed")
        log_message(f"Done flag written: {{done_flag_path}}")
    except Exception as e:
        log_message(f"Failed to write done flag: {{e}}")

log_message("Blender script started for GLB to OBJ with texture extraction")
log_message(f"Input GLB: {glb_path}")
log_message(f"Output OBJ: {obj_path}")
log_message(f"Output directory: {output_dir}")
log_message(f"Done flag: {done_flag_path}")

# 检查输入文件是否存在
if not os.path.exists(r"{glb_path}"):
    log_message(f"ERROR: Input GLB file not found: {glb_path}")
    write_done_flag()
    sys.exit(1)

# 清除默认场景
try:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    log_message("Default scene cleared")
except Exception as e:
    log_message(f"Failed to clear scene: {{e}}")

# 导入GLB文件
try:
    log_message("Starting GLB import...")
    bpy.ops.import_scene.gltf(filepath=r"{glb_path}")
    log_message("GLB imported successfully")
    
    # 检查导入的对象数量
    imported_objects = len(bpy.context.scene.objects)
    log_message(f"Imported objects count: {{imported_objects}}")
    
    # 检查材质数量
    materials_count = len(bpy.data.materials)
    log_message(f"Materials count: {{materials_count}}")
    
    # 检查图像数量
    images_count = len(bpy.data.images)
    log_message(f"Images count: {{images_count}}")
    
except Exception as e:
    log_message(f"Failed to import GLB: {{e}}")
    write_done_flag()
    sys.exit(1)

# 提取所有贴图文件
extracted_textures = []
try:
    log_message("Starting texture extraction...")
    
    for image in bpy.data.images:
        # 跳过内置图像（如Viewer Node等）
        if image.name in ['Render Result', 'Viewer Node']:
            continue
            
        log_message(f"Processing image: {{image.name}}, source: {{image.source}}, filepath: {{image.filepath}}, packed: {{image.packed_file is not None}}")
        
        # 确定输出文件名
        if image.filepath and image.filepath.strip():
            # 使用原始文件名
            texture_name = os.path.basename(image.filepath)
            if not texture_name:
                texture_name = f"{{image.name}}.png"
        else:
            # 使用图像名称，确保有扩展名
            texture_name = image.name
            if not texture_name.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff', '.exr', '.hdr')):
                texture_name += '.png'
        
        # 确保文件名有效（移除非法字符）
        texture_name = "".join(c for c in texture_name if c.isalnum() or c in "._-")
        if not texture_name:
            texture_name = f"texture_{{len(extracted_textures)}}.png"
        
        # 确保有扩展名
        if not any(texture_name.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff', '.exr', '.hdr']):
            texture_name += '.png'
        
        texture_path = os.path.join(output_dir, texture_name)
        
        # 尝试多种方法保存图像
        saved = False
        
        # 方法1：直接保存（适用于已加载的图像）
        if not saved:
            try:
                # 设置文件格式
                original_format = image.file_format
                if texture_name.lower().endswith('.png'):
                    image.file_format = 'PNG'
                elif texture_name.lower().endswith(('.jpg', '.jpeg')):
                    image.file_format = 'JPEG'
                elif texture_name.lower().endswith('.tga'):
                    image.file_format = 'TARGA'
                elif texture_name.lower().endswith('.bmp'):
                    image.file_format = 'BMP'
                else:
                    image.file_format = 'PNG'
                
                # 保存图像
                image.save_render(texture_path)
                log_message(f"Texture saved via save_render: {{texture_path}}")
                extracted_textures.append(texture_name)
                saved = True
                
                # 恢复原始格式
                image.file_format = original_format
                
            except Exception as e:
                log_message(f"save_render failed for {{image.name}}: {{e}}")
        
        # 方法2：使用filepath_raw保存（适用于有文件路径的图像）
        if not saved and hasattr(image, 'filepath_raw') and image.filepath_raw:
            try:
                image.filepath_raw = texture_path
                image.save()
                log_message(f"Texture saved via filepath_raw: {{texture_path}}")
                extracted_textures.append(texture_name)
                saved = True
            except Exception as e:
                log_message(f"filepath_raw save failed for {{image.name}}: {{e}}")
        
        # 方法3：处理打包的图像
        if not saved:
            try:
                # 如果图像没有打包，先打包
                if not image.packed_file:
                    image.pack()
                    log_message(f"Image {{image.name}} packed")
                
                # 如果有打包文件，解包到指定位置
                if image.packed_file:
                    # 设置解包路径
                    image.filepath = texture_path
                    image.unpack(method='WRITE_ORIGINAL')
                    
                    # 检查文件是否创建
                    if os.path.exists(texture_path):
                        log_message(f"Texture unpacked: {{texture_path}}")
                        extracted_textures.append(texture_name)
                        saved = True
                    else:
                        # 尝试WRITE_LOCAL方法
                        image.unpack(method='WRITE_LOCAL')
                        # 查找解包后的文件
                        for root, dirs, files in os.walk(output_dir):
                            for file in files:
                                if (file.startswith(image.name.split('.')[0]) or 
                                    file.startswith(texture_name.split('.')[0])) and \
                                   file.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tiff')):
                                    old_path = os.path.join(root, file)
                                    if old_path != texture_path:
                                        shutil.move(old_path, texture_path)
                                    log_message(f"Texture unpacked and moved: {{texture_path}}")
                                    extracted_textures.append(texture_name)
                                    saved = True
                                    break
                        if saved:
                            break
                            
            except Exception as e:
                log_message(f"pack/unpack failed for {{image.name}}: {{e}}")
        
        # 方法4：使用像素数据直接写入（最后的备选方案）
        if not saved and image.pixels:
            try:
                import numpy as np
                
                # 获取图像尺寸和像素数据
                width = image.size[0]
                height = image.size[1]
                channels = image.channels
                
                if width > 0 and height > 0 and len(image.pixels) > 0:
                    # 将像素数据转换为numpy数组
                    pixels = np.array(image.pixels[:])
                    pixels = pixels.reshape((height, width, channels))
                    
                    # 翻转Y轴（Blender的图像是上下颠倒的）
                    pixels = np.flipud(pixels)
                    
                    # 转换为0-255范围
                    if pixels.max() <= 1.0:
                        pixels = (pixels * 255).astype(np.uint8)
                    
                    # 保存为PNG
                    from PIL import Image as PILImage
                    if channels == 4:
                        pil_image = PILImage.fromarray(pixels, 'RGBA')
                    elif channels == 3:
                        pil_image = PILImage.fromarray(pixels, 'RGB')
                    else:
                        # 转换为RGB
                        if channels == 1:
                            pixels = np.stack([pixels[:,:,0]] * 3, axis=-1)
                        pil_image = PILImage.fromarray(pixels, 'RGB')
                    
                    pil_image.save(texture_path)
                    log_message(f"Texture saved via pixel data: {{texture_path}}")
                    extracted_textures.append(texture_name)
                    saved = True
                    
            except Exception as e:
                log_message(f"pixel data save failed for {{image.name}}: {{e}}")
        
        if not saved:
            log_message(f"Failed to save texture {{image.name}} with all methods")
    
    log_message(f"Texture extraction completed. Extracted {{len(extracted_textures)}} textures: {{extracted_textures}}")
    
except Exception as e:
    log_message(f"Texture extraction failed: {{e}}")
    import traceback
    log_message(f"Traceback: {{traceback.format_exc()}}")

# 导出为OBJ
try:
    log_message("Starting OBJ export...")
    bpy.ops.export_scene.obj(
        filepath=obj_output_path,
        use_materials=True,
        use_uvs=True,
        use_normals=True,
        use_triangles=False,
        path_mode='RELATIVE'
    )
    log_message("OBJ exported successfully")
    
    # 检查输出文件
    if os.path.exists(obj_output_path):
        file_size = os.path.getsize(obj_output_path)
        log_message(f"OBJ file created, size: {{file_size}} bytes")
    else:
        log_message("ERROR: OBJ file was not created")
        write_done_flag()
        sys.exit(1)
        
except Exception as e:
    log_message(f"Failed to export OBJ: {{e}}")
    write_done_flag()
    sys.exit(1)

log_message("Conversion completed successfully")
write_done_flag()
'''
            
            script_path = get_temp_file(".py")
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # 使用Windows的start命令启动Blender，让它独立运行
            cmd = f'start "" "{blender_exe}" --background --python "{script_path}"'
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Starting Blender process independently: {cmd}\n")
            
            # 启动Blender进程（不阻塞）
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 等待Blender完成，通过检查完成标记文件
            max_wait_time = 180  # 最大等待时间3分钟
            wait_interval = 1    # 检查间隔1秒
            waited_time = 0
            blender_completed = False
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Waiting for Blender to complete (max {max_wait_time}s)...\n")
                logf.write(f"Done flag path: {done_flag_path}\n")
                logf.write(f"OBJ output path: {obj_path}\n")
            
            # 记录开始等待的时间
            start_wait_time = time.time()
            
            while waited_time < max_wait_time:
                # 首先检查完成标记文件
                done_flag_exists = os.path.exists(done_flag_path)
                obj_exists = os.path.exists(obj_path)
                obj_size = os.path.getsize(obj_path) if obj_exists else 0
                
                # 记录详细的检查状态
                if waited_time % 10 == 0:  # 每10秒记录一次状态
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Wait status at {waited_time}s: done_flag={done_flag_exists}, obj_exists={obj_exists}, obj_size={obj_size}\n")
                
                # 检查完成条件：完成标记文件存在且OBJ文件有效
                if done_flag_exists and obj_exists and obj_size > 0:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Blender completed successfully after {waited_time}s\n")
                        logf.write(f"Final OBJ size: {obj_size} bytes\n")
                    blender_completed = True
                    break
                
                # 如果只有OBJ文件但没有完成标记，等待更长时间确认
                elif obj_exists and obj_size > 0 and waited_time > 30:
                    # 等待30秒后，如果OBJ文件存在且大小稳定，认为完成
                    time.sleep(2)  # 再等2秒确认文件大小稳定
                    new_obj_size = os.path.getsize(obj_path) if os.path.exists(obj_path) else 0
                    if new_obj_size == obj_size and obj_size > 0:
                        with open(log_file, "a", encoding="utf-8") as logf:
                            logf.write(f"OBJ file stable after {waited_time}s (size: {obj_size} bytes), assuming completion\n")
                        blender_completed = True
                        break
                
                time.sleep(wait_interval)
                waited_time += 1
            
            if not blender_completed:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Blender timeout after {max_wait_time}s\n")
                    # 尝试强制终止可能残留的Blender进程
                    logf.write("Attempting to terminate any remaining Blender processes...\n")
                
                # 强制终止Blender进程
                try:
                    for p in psutil.process_iter(['name', 'exe', 'cmdline']):
                        try:
                            if p.info['name'] and 'blender' in p.info['name'].lower():
                                # 检查是否是我们启动的进程（通过脚本路径）
                                if p.info['cmdline'] and script_path in ' '.join(p.info['cmdline']):
                                    p.terminate()
                                    with open(log_file, "a", encoding="utf-8") as logf:
                                        logf.write(f"Terminated Blender process: {p.pid}\n")
                        except Exception:
                            continue
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to terminate Blender processes: {e}\n")
            
            # 收集提取的贴图文件
            output_dir = os.path.dirname(obj_path)
            for filename in os.listdir(output_dir):
                file_path = os.path.join(output_dir, filename)
                if os.path.isfile(file_path) and is_texture_file(filename):
                    extracted_textures.append(file_path)
            
            # 清理临时文件
            try:
                os.remove(script_path)
            except Exception:
                pass
            try:
                if os.path.exists(done_flag_path):
                    os.remove(done_flag_path)
            except Exception:
                pass
            
            # 在Blender调试日志中添加结束标记
            with open(blender_debug_log, "a", encoding="utf-8") as debug_logf:
                debug_logf.write(f"===== Blender Conversion End =====\n\n")
            
            # 检查OBJ文件是否成功创建
            if os.path.exists(obj_path) and os.path.getsize(obj_path) > 0:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Blender conversion successful, extracted {len(extracted_textures)} textures\n")
                    for tex in extracted_textures:
                        logf.write(f"  - {tex}\n")
                return extracted_textures
            else:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write("Blender conversion failed, falling back to trimesh\n")
                # 如果 Blender 失败，确保强制终止任何残留进程
                try:
                    import psutil
                    for p in psutil.process_iter(['name', 'exe', 'cmdline']):
                        try:
                            if p.info['name'] and 'blender' in p.info['name'].lower():
                                if p.info['cmdline'] and script_path in ' '.join(p.info['cmdline']):
                                    p.terminate()
                                    with open(log_file, "a", encoding="utf-8") as logf:
                                        logf.write(f"Force terminated Blender process: {p.pid}\n")
                        except Exception:
                            continue
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to terminate Blender processes: {e}\n")
        else:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write("Blender not found, using trimesh\n")
    
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Blender conversion error: {e}, falling back to trimesh\n")
    
    # 使用trimesh作为备选方案（但trimesh无法提取嵌入的贴图）
    try:
        start_time = time.time()
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Loading mesh with trimesh...\n")
        
        mesh = trimesh.load(glb_path)
        
        load_time = time.time() - start_time
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Mesh loaded in {load_time:.2f} seconds\n")
            logf.write(f"Mesh type: {type(mesh)}\n")
            if hasattr(mesh, 'vertices'):
                logf.write(f"Vertices: {len(mesh.vertices)}\n")
            if hasattr(mesh, 'faces'):
                logf.write(f"Faces: {len(mesh.faces)}\n")
        
        # 导出为OBJ
        start_time = time.time()
        mesh.export(obj_path)
        export_time = time.time() - start_time
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"OBJ exported in {export_time:.2f} seconds\n")
            logf.write(f"Output file size: {os.path.getsize(obj_path)} bytes\n")
            logf.write("Trimesh conversion completed successfully (no texture extraction)\n")
        
        # trimesh无法提取嵌入贴图，返回空列表
        return []
    
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Trimesh conversion failed: {e}\n")
        raise RuntimeError(f"GLB to OBJ conversion failed: {e}")

def glb_to_obj(glb_path: str, obj_path: str) -> None:
    """
    用trimesh将GLB转OBJ，保留基本几何和材质。
    Args:
        glb_path (str): 输入GLB文件路径
        obj_path (str): 输出OBJ文件路径
    Raises:
        RuntimeError: 转换失败时抛出
    """
    # 调用增强版本的转换函数，但忽略返回的贴图列表
    glb_to_obj_with_textures(glb_path, obj_path)

def obj_to_glb(obj_path: str, glb_path: str) -> None:
    """
    将OBJ文件转换为GLB文件，优先使用Blender以更好地处理材质和贴图，
    如果Blender不可用则使用trimesh作为备选方案。
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
    
    # 首先尝试使用Blender进行转换
    try:
        # 自动检测Blender 3.6可执行文件
        blender_exe = get_blender_executable_with_fallback()
        
        # 记录检测结果
        with open(log_file, "a", encoding="utf-8") as logf:
            if blender_exe:
                logf.write(f"Blender 3.6 detected at: {blender_exe}\n")
            else:
                logf.write("Blender 3.6 not found, will use fallback method\n")
        
        if blender_exe:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Using Blender: {blender_exe}\n")
            
            # 创建完成标记文件路径（确保是唯一的）
            done_flag_path = get_temp_file(".done")
            
            # 确保完成标记文件不存在（清理之前可能残留的文件）
            if os.path.exists(done_flag_path):
                try:
                    os.remove(done_flag_path)
                except Exception:
                    pass
            
            # 创建Blender调试日志文件
            blender_debug_log = os.path.join(LOG_DIR, "blender_debug.log")
            
            # 在日志文件中插入分隔标记
            with open(blender_debug_log, "a", encoding="utf-8") as debug_logf:
                debug_logf.write(f"\n===== {timestamp} Blender OBJ to GLB Conversion =====\n")
                debug_logf.write(f"Input OBJ: {obj_path}\n")
                debug_logf.write(f"Output GLB: {glb_path}\n")
                debug_logf.write(f"Blender executable: {blender_exe}\n")
                debug_logf.write(f"Done flag path: {done_flag_path}\n")
            
            # 创建Blender脚本
            script_content = f'''
import bpy
import os
import sys
import time

# 重定向输出到调试日志文件
debug_log_path = r"{blender_debug_log}"
done_flag_path = r"{done_flag_path}"
glb_output_path = r"{glb_path}"

def log_message(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(debug_log_path, "a", encoding="utf-8") as f:
        f.write(f"[{{timestamp}}] {{message}}\\n")

def write_done_flag():
    try:
        with open(done_flag_path, "w", encoding="utf-8") as f:
            f.write("completed")
        log_message(f"Done flag written: {{done_flag_path}}")
    except Exception as e:
        log_message(f"Failed to write done flag: {{e}}")

log_message("Blender script started")
log_message(f"Input OBJ: {obj_path}")
log_message(f"Output GLB: {glb_path}")
log_message(f"Done flag: {done_flag_path}")

# 检查输入文件是否存在
if not os.path.exists(r"{obj_path}"):
    log_message(f"ERROR: Input OBJ file not found: {obj_path}")
    write_done_flag()
    sys.exit(1)

# 清除默认场景
try:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    log_message("Default scene cleared")
except Exception as e:
    log_message(f"Failed to clear scene: {{e}}")

# 导入OBJ文件
try:
    log_message("Starting OBJ import...")
    bpy.ops.import_scene.obj(filepath=r"{obj_path}")
    log_message("OBJ imported successfully")
    
    # 检查导入的对象数量
    imported_objects = len(bpy.context.scene.objects)
    log_message(f"Imported objects count: {{imported_objects}}")
    
    # 检查材质数量
    materials_count = len(bpy.data.materials)
    log_message(f"Materials count: {{materials_count}}")
    
    # 检查图像数量
    images_count = len(bpy.data.images)
    log_message(f"Images count: {{images_count}}")
    
except Exception as e:
    log_message(f"Failed to import OBJ: {{e}}")
    write_done_flag()
    sys.exit(1)

# 处理材质和贴图关联
try:
    log_message("Processing materials and textures...")
    
    # 获取OBJ文件所在目录
    obj_dir = os.path.dirname(r"{obj_path}")
    log_message(f"OBJ directory: {{obj_dir}}")
    
    # 遍历所有材质，确保贴图正确关联
    for material in bpy.data.materials:
        log_message(f"Processing material: {{material.name}}")
        
        # 确保材质使用节点
        if not material.use_nodes:
            material.use_nodes = True
            log_message(f"Enabled nodes for material: {{material.name}}")
        
        # 获取材质节点树
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # 查找主着色器节点
        principled_bsdf = None
        for node in nodes:
            if node.type == 'BSDF_PRINCIPLED':
                principled_bsdf = node
                break
        
        if not principled_bsdf:
            log_message(f"No Principled BSDF found for material: {{material.name}}")
            continue
        
        # 查找现有的图像纹理节点
        image_texture_nodes = [node for node in nodes if node.type == 'TEX_IMAGE']
        log_message(f"Found {{len(image_texture_nodes)}} image texture nodes in material: {{material.name}}")
        
        # 如果没有图像纹理节点，尝试创建
        if not image_texture_nodes:
            # 查找可能的贴图文件
            material_base_name = material.name.lower()
            potential_textures = []
            
            # 搜索OBJ目录中的贴图文件
            try:
                for file in os.listdir(obj_dir):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.bmp')):
                        potential_textures.append(os.path.join(obj_dir, file))
                        log_message(f"Found potential texture: {{file}}")
            except Exception as e:
                log_message(f"Failed to list directory {{obj_dir}}: {{e}}")
            
            # 按优先级排序贴图文件
            color_textures = []
            normal_textures = []
            orm_textures = []
            other_textures = []
            
            for texture_path in potential_textures:
                texture_name = os.path.basename(texture_path).lower()
                
                # 跳过dummy贴图
                if 'dummy' in texture_name:
                    log_message(f"Skipping dummy texture: {{texture_name}}")
                    continue
                
                # 按类型分类
                if any(keyword in texture_name for keyword in ['color', 'diffuse', 'albedo', 'basecolor']):
                    color_textures.append(texture_path)
                elif any(keyword in texture_name for keyword in ['normal', 'norm']):
                    normal_textures.append(texture_path)
                elif 'orm' in texture_name:
                    orm_textures.append(texture_path)
                else:
                    other_textures.append(texture_path)
            
            # 按优先级处理贴图
            processed_types = set()
            
            # 1. 处理基础颜色贴图（优先级最高）
            if color_textures and 'base_color' not in processed_types:
                texture_path = color_textures[0]  # 使用第一个找到的颜色贴图
                try:
                    image = bpy.data.images.load(texture_path)
                    log_message(f"Loaded color texture: {{os.path.basename(texture_path)}}")
                    
                    texture_node = nodes.new(type='ShaderNodeTexImage')
                    texture_node.image = image
                    texture_node.location = (-300, 200)
                    
                    links.new(texture_node.outputs['Color'], principled_bsdf.inputs['Base Color'])
                    log_message(f"Connected {{os.path.basename(texture_path)}} to Base Color")
                    processed_types.add('base_color')
                    
                except Exception as e:
                    log_message(f"Failed to process color texture {{texture_path}}: {{e}}")
            
            # 2. 处理法线贴图
            if normal_textures and 'normal' not in processed_types:
                texture_path = normal_textures[0]
                try:
                    image = bpy.data.images.load(texture_path)
                    log_message(f"Loaded normal texture: {{os.path.basename(texture_path)}}")
                    
                    texture_node = nodes.new(type='ShaderNodeTexImage')
                    texture_node.image = image
                    texture_node.location = (-300, -100)
                    
                    # 设置为非颜色数据
                    image.colorspace_settings.name = 'Non-Color'
                    
                    normal_map_node = nodes.new(type='ShaderNodeNormalMap')
                    normal_map_node.location = (-150, -100)
                    links.new(texture_node.outputs['Color'], normal_map_node.inputs['Color'])
                    links.new(normal_map_node.outputs['Normal'], principled_bsdf.inputs['Normal'])
                    log_message(f"Connected {{os.path.basename(texture_path)}} to Normal")
                    processed_types.add('normal')
                    
                except Exception as e:
                    log_message(f"Failed to process normal texture {{texture_path}}: {{e}}")
            
            # 3. 处理ORM贴图
            if orm_textures and 'orm' not in processed_types:
                texture_path = orm_textures[0]
                try:
                    image = bpy.data.images.load(texture_path)
                    log_message(f"Loaded ORM texture: {{os.path.basename(texture_path)}}")
                    
                    texture_node = nodes.new(type='ShaderNodeTexImage')
                    texture_node.image = image
                    texture_node.location = (-300, -400)
                    
                    # 设置为非颜色数据
                    image.colorspace_settings.name = 'Non-Color'
                    
                    # 创建分离RGB节点
                    separate_rgb = nodes.new(type='ShaderNodeSeparateRGB')
                    separate_rgb.location = (-150, -400)
                    links.new(texture_node.outputs['Color'], separate_rgb.inputs['Image'])
                    
                    # 连接到对应通道 (ORM = Occlusion-Roughness-Metallic)
                    links.new(separate_rgb.outputs['G'], principled_bsdf.inputs['Roughness'])  # Green = Roughness
                    links.new(separate_rgb.outputs['B'], principled_bsdf.inputs['Metallic'])   # Blue = Metallic
                    # Red通道(Occlusion)可以连接到AO，但Principled BSDF没有直接的AO输入
                    
                    log_message(f"Connected {{os.path.basename(texture_path)}} as ORM texture (G->Roughness, B->Metallic)")
                    processed_types.add('orm')
                    
                except Exception as e:
                    log_message(f"Failed to process ORM texture {{texture_path}}: {{e}}")
            
            # 4. 处理其他贴图（如果没有找到主要贴图类型）
            if not processed_types and other_textures:
                # 如果没有处理任何主要贴图，将第一个其他贴图作为基础颜色
                texture_path = other_textures[0]
                texture_name = os.path.basename(texture_path).lower()
                
                # 再次跳过dummy贴图
                if 'dummy' not in texture_name:
                    try:
                        image = bpy.data.images.load(texture_path)
                        log_message(f"Loaded fallback texture: {{os.path.basename(texture_path)}}")
                        
                        texture_node = nodes.new(type='ShaderNodeTexImage')
                        texture_node.image = image
                        texture_node.location = (-300, 200)
                        
                        links.new(texture_node.outputs['Color'], principled_bsdf.inputs['Base Color'])
                        log_message(f"Connected {{os.path.basename(texture_path)}} to Base Color (fallback)")
                        
                    except Exception as e:
                        log_message(f"Failed to process fallback texture {{texture_path}}: {{e}}")
        else:
            # 检查现有图像纹理节点的图像是否有效
            for texture_node in image_texture_nodes:
                if texture_node.image:
                    log_message(f"Existing texture node has image: {{texture_node.image.name}}")
                else:
                    log_message(f"Existing texture node has no image assigned")
    
    log_message("Material and texture processing completed")
    
except Exception as e:
    log_message(f"Failed to process materials and textures: {{e}}")
    # 继续执行，不中断流程

# 导出为GLB
try:
    log_message("Starting GLB export...")
    bpy.ops.export_scene.gltf(
        filepath=glb_output_path,
        export_format='GLB',
        export_materials='EXPORT',
        export_texcoords=True,
        export_normals=True,
        export_colors=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False
    )
    log_message("GLB exported successfully")
    
    # 检查输出文件
    if os.path.exists(glb_output_path):
        file_size = os.path.getsize(glb_output_path)
        log_message(f"GLB file created, size: {{file_size}} bytes")
    else:
        log_message("ERROR: GLB file was not created")
        write_done_flag()
        sys.exit(1)
        
except Exception as e:
    log_message(f"Failed to export GLB: {{e}}")
    write_done_flag()
    sys.exit(1)

log_message("Conversion completed successfully")
write_done_flag()
'''
            
            script_path = get_temp_file(".py")
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
            
            # 使用Windows的start命令启动Blender，让它独立运行
            cmd = f'start "" "{blender_exe}" --background --python "{script_path}"'
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Starting Blender process independently: {cmd}\n")
            
            # 启动Blender进程（不阻塞）
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 等待Blender完成，通过检查完成标记文件
            max_wait_time = 180  # 最大等待时间3分钟
            wait_interval = 1    # 检查间隔1秒
            waited_time = 0
            blender_completed = False
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Waiting for Blender to complete (max {max_wait_time}s)...\n")
                logf.write(f"Done flag path: {done_flag_path}\n")
                logf.write(f"GLB output path: {glb_path}\n")
            
            # 记录开始等待的时间
            start_wait_time = time.time()
            
            while waited_time < max_wait_time:
                # 首先检查完成标记文件
                done_flag_exists = os.path.exists(done_flag_path)
                glb_exists = os.path.exists(glb_path)
                glb_size = os.path.getsize(glb_path) if glb_exists else 0
                
                # 记录详细的检查状态
                if waited_time % 10 == 0:  # 每10秒记录一次状态
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Wait status at {waited_time}s: done_flag={done_flag_exists}, glb_exists={glb_exists}, glb_size={glb_size}\n")
                
                # 检查完成条件：完成标记文件存在且GLB文件有效
                if done_flag_exists and glb_exists and glb_size > 0:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Blender completed successfully after {waited_time}s\n")
                        logf.write(f"Final GLB size: {glb_size} bytes\n")
                    blender_completed = True
                    break
                
                # 如果只有GLB文件但没有完成标记，等待更长时间确认
                elif glb_exists and glb_size > 0 and waited_time > 30:
                    # 等待30秒后，如果GLB文件存在且大小稳定，认为完成
                    time.sleep(2)  # 再等2秒确认文件大小稳定
                    new_glb_size = os.path.getsize(glb_path) if os.path.exists(glb_path) else 0
                    if new_glb_size == glb_size and glb_size > 0:
                        with open(log_file, "a", encoding="utf-8") as logf:
                            logf.write(f"GLB file stable after {waited_time}s (size: {glb_size} bytes), assuming completion\n")
                        blender_completed = True
                        break
                
                time.sleep(wait_interval)
                waited_time += 1
            
            if not blender_completed:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write(f"Blender timeout after {max_wait_time}s\n")
                    # 尝试强制终止可能残留的Blender进程
                    logf.write("Attempting to terminate any remaining Blender processes...\n")
                
                # 强制终止Blender进程
                try:
                    for p in psutil.process_iter(['name', 'exe', 'cmdline']):
                        try:
                            if p.info['name'] and 'blender' in p.info['name'].lower():
                                # 检查是否是我们启动的进程（通过脚本路径）
                                if p.info['cmdline'] and script_path in ' '.join(p.info['cmdline']):
                                    p.terminate()
                                    with open(log_file, "a", encoding="utf-8") as logf:
                                        logf.write(f"Terminated Blender process: {p.pid}\n")
                        except Exception:
                            continue
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to terminate Blender processes: {e}\n")
            
            # 清理临时文件
            try:
                os.remove(script_path)
            except Exception:
                pass
            try:
                if os.path.exists(done_flag_path):
                    os.remove(done_flag_path)
            except Exception:
                pass
            
            # 在Blender调试日志中添加结束标记
            with open(blender_debug_log, "a", encoding="utf-8") as debug_logf:
                debug_logf.write(f"===== Blender Conversion End =====\n\n")
            
            # 检查GLB文件是否成功创建
            if os.path.exists(glb_path) and os.path.getsize(glb_path) > 0:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write("Blender conversion successful\n")
                return
            else:
                with open(log_file, "a", encoding="utf-8") as logf:
                    logf.write("Blender conversion failed, falling back to trimesh\n")
                # 如果 Blender 失败，确保强制终止任何残留进程
                try:
                    import psutil
                    for p in psutil.process_iter(['name', 'exe', 'cmdline']):
                        try:
                            if p.info['name'] and 'blender' in p.info['name'].lower():
                                if p.info['cmdline'] and script_path in ' '.join(p.info['cmdline']):
                                    p.terminate()
                                    with open(log_file, "a", encoding="utf-8") as logf:
                                        logf.write(f"Force terminated Blender process: {p.pid}\n")
                        except Exception:
                            continue
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to terminate Blender processes: {e}\n")
        else:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write("Blender not found, using trimesh\n")
    
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Blender conversion error: {e}, falling back to trimesh\n")
    
    # 使用trimesh作为备选方案
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
                logf.write(f"Vertices: {len(mesh.vertices)}\n")
            if hasattr(mesh, 'faces'):
                logf.write(f"Faces: {len(mesh.faces)}\n")
        
        # 导出为GLB
        start_time = time.time()
        mesh.export(glb_path)
        export_time = time.time() - start_time
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"GLB exported in {export_time:.2f} seconds\n")
            logf.write(f"Output file size: {os.path.getsize(glb_path)} bytes\n")
            logf.write("Trimesh conversion completed successfully\n")
    
    except Exception as e:
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Trimesh conversion failed: {e}\n")
        raise RuntimeError(f"OBJ to GLB conversion failed: {e}")

def enhanced_is_texture_file(filename: str) -> bool:
    """
    增强版贴图文件识别函数，支持更多贴图类型和命名约定。
    Args:
        filename (str): 文件名
    Returns:
        bool: 是否为贴图文件
    """
    # 标准贴图扩展名（包括更多格式）
    texture_extensions = [
        '.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tiff', '.tif',
        '.dds', '.hdr', '.exr', '.webp', '.ktx', '.ktx2', '.basis',
        '.psd', '.targa', '.sgi', '.pic', '.iff', '.ppm', '.pgm', '.pbm'
    ]
    
    lower_name = filename.lower()
    
    # 检查扩展名
    if not any(lower_name.endswith(ext) for ext in texture_extensions):
        return False
    
    # 排除明显的非贴图关键词
    non_texture_keywords = [
        'screenshot', 'capture', 'icon', 'logo', 'banner', 'thumb', 'preview',
        'ui', 'gui', 'button', 'menu', 'cursor', 'font'
    ]
    for non_keyword in non_texture_keywords:
        if non_keyword in lower_name:
            return False
    
    # 检查常见的贴图命名约定（扩展列表）
    texture_keywords = [
        # 基础贴图
        'diffuse', 'albedo', 'basecolor', 'base_color', 'color', 'col', 'diff',
        'base', 'main', 'primary',
        
        # 法线贴图
        'normal', 'normalgl', 'norm', 'nrm', 'bump', 'height', 'disp', 'displacement',
        
        # 材质属性贴图
        'roughness', 'rough', 'rgh', 'gloss', 'glossiness',
        'metallic', 'metal', 'met', 'metalness',
        'specular', 'spec', 'reflection', 'refl',
        
        # 环境贴图
        'ambient', 'ao', 'occlusion', 'cavity',
        
        # 发光贴图
        'emission', 'emissive', 'emit', 'glow', 'light',
        
        # 透明度贴图
        'opacity', 'alpha', 'transparency', 'mask',
        
        # 组合贴图
        'orm',  # Occlusion-Roughness-Metallic
        'rma',  # Roughness-Metallic-AO
        'arm',  # AO-Roughness-Metallic
        
        # 细节贴图
        'detail', 'micro', 'fine', 'secondary',
        
        # 其他常见类型
        'subsurface', 'sss', 'transmission', 'clearcoat',
        'anisotropy', 'sheen', 'iridescence',
        
        # 通用标识
        'texture', 'tex', 'map', 'material', 'mat', 'surface', 'skin',
        
        # 数字编号（material_0, texture_1等）
        'material_', 'texture_', 'tex_', 'mat_', 'img_', 'image_'
    ]
    
    # 如果文件名包含任何贴图关键词，认为是贴图文件
    for keyword in texture_keywords:
        if keyword in lower_name:
            return True
    
    # 检查数字模式（如material0, tex1, image2等）
    import re
    number_patterns = [
        r'material\d+', r'texture\d+', r'tex\d+', r'mat\d+', 
        r'img\d+', r'image\d+', r'map\d+', r'surface\d+'
    ]
    for pattern in number_patterns:
        if re.search(pattern, lower_name):
            return True
    
    # 如果文件名很短且是图片格式，很可能是贴图
    name_without_ext = os.path.splitext(lower_name)[0]
    if len(name_without_ext) <= 12 and any(lower_name.endswith(ext) for ext in texture_extensions):
        return True
    
    # 如果是常见的图片格式且文件名不包含明显的非贴图词汇，也认为是贴图
    common_image_exts = ['.jpg', '.jpeg', '.png', '.bmp', '.tga', '.tiff']
    if any(lower_name.endswith(ext) for ext in common_image_exts):
        return True
    
    return False

# 更新原有的is_texture_file函数
def is_texture_file(filename: str) -> bool:
    """
    判断文件是否为贴图文件，基于文件扩展名和命名约定。
    支持标准贴图扩展名以及现代PBR工作流中的命名约定。
    Args:
        filename (str): 文件名
    Returns:
        bool: 是否为贴图文件
    """
    return enhanced_is_texture_file(filename)

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

def restore_obj_material(obj_path: str, original_obj_path: str):
    """
    将原始OBJ的mtl和贴图引用复制到新OBJ，修正mtllib和usemtl，保证贴图不丢失。
    确保所有贴图都在temp目录中处理，最终GLB包含完整材质。
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
    
    # 优先在temp目录查找，再在原始目录查找
    temp_mtl_path = os.path.join(TEMP_DIR, mtl_file)
    orig_mtl_path = os.path.join(orig_dir, mtl_file)
    
    mtl_source_path = None
    if os.path.exists(temp_mtl_path):
        mtl_source_path = temp_mtl_path
    elif os.path.exists(orig_mtl_path):
        mtl_source_path = orig_mtl_path
    
    if not mtl_source_path:
        return
        
    # 复制MTL文件到新目录
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
            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal', 'map_normalgl', 'map_orm', 'map_roughness', 'map_metallic', 'map_ao', 'map_emissive', 'map_opacity', 'map_displacement', 'map_height')):
                parts = line.split()
                if len(parts) > 1:
                    tex_file = parts[-1]  # 取最后一个部分作为文件名
                    # 处理可能的路径分隔符
                    tex_file = tex_file.replace('\\', '/').split('/')[-1]
                    
                    # 优先在temp目录查找贴图文件，再在原始目录查找
                    tex_source_path = None
                    temp_tex_path = os.path.join(TEMP_DIR, tex_file)
                    orig_tex_path = os.path.join(orig_dir, tex_file)
                    
                    if os.path.exists(temp_tex_path):
                        tex_source_path = temp_tex_path
                    elif os.path.exists(orig_tex_path):
                        tex_source_path = orig_tex_path
                    
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
    temp_files: list = None,
    texture_files: list = None
) -> str:
    """
    为处理后的模型创建归档文件夹，包含模型文件、材质、贴图和处理信息。
    Args:
        model_path (str): 输出模型文件路径
        original_input (str): 原始输入模型路径/URL
        processing_info (dict): 处理信息（面数、参数等）
        processing_log_file (str): 本次处理的日志文件路径
        temp_files (list): 临时文件列表，用于查找贴图文件
        texture_files (list): 要归档的贴图文件路径列表
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

        # 2. 复制所有收集到的贴图文件
        copied_textures = []
        
        with open(archive_log, "a", encoding="utf-8") as logf:
            logf.write("Starting texture file copying...\n")
            logf.write(f"Total texture files to copy: {len(texture_files) if texture_files else 0}\n")
        
        if texture_files:
            for texture_path in texture_files:
                if os.path.exists(texture_path) and os.path.isfile(texture_path):
                    try:
                        filename = os.path.basename(texture_path)
                        # 避免重复复制同名文件
                        if filename not in copied_textures:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Copying texture: {filename} from {texture_path}\n")
                            shutil.copy2(texture_path, textures_dir)
                            copied_textures.append(filename)
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Texture copied: {filename}\n")
                        else:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Skipping duplicate texture: {filename}\n")
                    except Exception as e:
                        with open(archive_log, "a", encoding="utf-8") as logf:
                            logf.write(f"Failed to copy texture {texture_path}: {e}\n")
                        continue
        
        # 备用方案：如果没有收集到贴图文件，从temp和模型目录搜索
        if not copied_textures:
            with open(archive_log, "a", encoding="utf-8") as logf:
                logf.write("No textures copied from provided list, searching directories...\n")
            
            # 搜索temp目录
            if os.path.exists(TEMP_DIR):
                temp_textures = collect_texture_files_from_directory(TEMP_DIR)
                for texture_path in temp_textures:
                    try:
                        filename = os.path.basename(texture_path)
                        if filename not in copied_textures:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Copying texture from temp: {filename}\n")
                            shutil.copy2(texture_path, textures_dir)
                            copied_textures.append(filename)
                    except Exception as e:
                        with open(archive_log, "a", encoding="utf-8") as logf:
                            logf.write(f"Failed to copy temp texture {texture_path}: {e}\n")
            
            # 搜索模型目录
            if model_path.lower().endswith('.obj'):
                model_dir = os.path.dirname(model_path)
                model_textures = collect_texture_files_from_directory(model_dir)
                for texture_path in model_textures:
                    try:
                        filename = os.path.basename(texture_path)
                        if filename not in copied_textures:
                            with open(archive_log, "a", encoding="utf-8") as logf:
                                logf.write(f"Copying texture from model dir: {filename}\n")
                            shutil.copy2(texture_path, textures_dir)
                            copied_textures.append(filename)
                    except Exception as e:
                        with open(archive_log, "a", encoding="utf-8") as logf:
                            logf.write(f"Failed to copy model dir texture {texture_path}: {e}\n")
        
        with open(archive_log, "a", encoding="utf-8") as logf:
            logf.write(f"Texture copying completed. Total copied: {len(copied_textures)}\n")

        # 3. 复制MTL文件（如果是OBJ模型）
        if model_path.lower().endswith('.obj'):
            source_dir = os.path.dirname(model_path)
            model_base = os.path.splitext(os.path.basename(model_path))[0]
            
            # 查找并复制MTL文件
            possible_mtl = os.path.join(source_dir, f"{model_base}.mtl")
            if os.path.exists(possible_mtl):
                try:
                    shutil.copy2(possible_mtl, model_dir)
                    with open(archive_log, "a", encoding="utf-8") as logf:
                        logf.write(f"MTL file copied: {os.path.basename(possible_mtl)}\n")
                except Exception as e:
                    with open(archive_log, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to copy MTL file: {e}\n")
            else:
                # 尝试查找temp目录中的MTL文件
                temp_mtl = os.path.join(TEMP_DIR, f"{model_base}.mtl")
                if os.path.exists(temp_mtl):
                    try:
                        shutil.copy2(temp_mtl, model_dir)
                        with open(archive_log, "a", encoding="utf-8") as logf:
                            logf.write(f"MTL file copied from temp: {os.path.basename(temp_mtl)}\n")
                    except Exception as e:
                        with open(archive_log, "a", encoding="utf-8") as logf:
                            logf.write(f"Failed to copy MTL file from temp: {e}\n")

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
    operation: str = "simplify",
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
            - "simplify": 纯减面，保持原有网格结构，保持边缘清晰（默认）
            - "auto": 自动选择（水密模型用simplify，有问题的用remesh）
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
    
    # 在处理开始前收集所有贴图文件（支持GLB贴图提取）
    texture_files_for_archive = collect_all_texture_files(input_model, additional_files)
    
    # 如果输入是GLB文件，预先提取贴图到temp目录
    if input_model.lower().endswith('.glb') and os.path.exists(input_model):
        try:
            temp_obj_for_extraction = get_temp_file('.obj')
            extracted_textures = glb_to_obj_with_textures(input_model, temp_obj_for_extraction)
            
            # 将提取的贴图添加到归档列表
            for texture_path in extracted_textures:
                if os.path.exists(texture_path) and texture_path not in texture_files_for_archive:
                    texture_files_for_archive.append(texture_path)
            
            # 清理临时OBJ文件
            try:
                if os.path.exists(temp_obj_for_extraction):
                    os.remove(temp_obj_for_extraction)
                temp_mtl = temp_obj_for_extraction.replace('.obj', '.mtl')
                if os.path.exists(temp_mtl):
                    os.remove(temp_mtl)
            except Exception:
                pass
                
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"WARNING: Failed to pre-extract GLB textures: {e}\n")
    
    try:
        with open(log_file, "w", encoding="utf-8") as logf:
            logf.write(f"Starting model processing\n")
            logf.write(f"Input: {input_model}\n")
            logf.write(f"Target faces: {target_faces}\n")
            logf.write(f"Operation: {operation}\n")
            logf.write(f"Mode: {mode}\n")
            logf.write(f"Preserve UV: {preserve_uv}\n")
            logf.write(f"Create archive: {create_archive}\n")
            logf.write(f"Initial texture files collected: {len(texture_files_for_archive)}\n")
            for tex_file in texture_files_for_archive:
                logf.write(f"  - {tex_file}\n")
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
            
            # 若输入为GLB，先转OBJ
            if local_input.lower().endswith(".glb"):
                obj_in = get_temp_file(".obj")
                glb_to_obj(local_input, obj_in)
                temp_files.append(obj_in)
            else:
                obj_in = local_input
        else:
            # 本地文件
            local_input = input_model
            
            # 确保使用绝对路径
            if not os.path.isabs(local_input):
                local_input = os.path.abspath(local_input)
            
            # 若输入为GLB，先转OBJ
            if local_input.lower().endswith(".glb"):
                obj_in = get_temp_file(".obj")
                glb_to_obj(local_input, obj_in)
                temp_files.append(obj_in)
            else:
                # 本地OBJ文件，复制到temp目录
                obj_in = process_obj_with_materials(local_input, additional_files)
                temp_files.append(obj_in)

        # 更新贴图文件列表，包含temp目录中新复制的文件
        temp_texture_files = collect_texture_files_from_directory(TEMP_DIR)
        for tex_file in temp_texture_files:
            if tex_file not in texture_files_for_archive:
                texture_files_for_archive.append(tex_file)

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

        # 7. 确保所有贴图都在final_obj的同一目录中，以便GLB转换时正确嵌入
        ensure_textures_in_obj_dir(final_obj)
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Ensured all textures are in OBJ directory for GLB conversion.\n")
        
        # 最终收集所有贴图文件（包括处理过程中生成的）
        final_obj_dir = os.path.dirname(final_obj)
        final_texture_files = collect_texture_files_from_directory(final_obj_dir)
        temp_texture_files = collect_texture_files_from_directory(TEMP_DIR)
        
        # 合并所有贴图文件，去重
        all_final_textures = final_texture_files + temp_texture_files
        for tex_file in all_final_textures:
            if tex_file not in texture_files_for_archive:
                texture_files_for_archive.append(tex_file)
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Collected {len(texture_files_for_archive)} texture files for archive.\n")

        # 8. 输出为GLB
        temp_glb = get_temp_file(".glb")
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Starting OBJ to GLB conversion...\n")
            logf.write("IMPORTANT: Temp directory will NOT be cleaned until GLB conversion is complete.\n")
        
        # 确保 obj_to_glb 真正等待 Blender 完成
        obj_to_glb(final_obj, temp_glb)
        temp_files.append(temp_glb)
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("OBJ to GLB conversion completed.\n")
            logf.write(f"GLB file exists: {os.path.exists(temp_glb)}\n")
            if os.path.exists(temp_glb):
                logf.write(f"GLB file size: {os.path.getsize(temp_glb)} bytes\n")

        # 9. 移动到输出目录
        orig_name = get_original_name(input_model)
        output_name = os.path.splitext(orig_name)[0] + f"_{actual_operation}.glb"
        output_model = os.path.join(OUTPUT_DIR, output_name)
        move_and_cleanup(temp_glb, output_model)
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Model moved to output directory: {output_model}\n")
        
        # 10. 创建归档（可选）
        archive_path = None
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
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write("Creating archive...\n")
            
            archive_path = create_model_archive(
                output_model, 
                input_model, 
                processing_info, 
                processing_log_file=log_file,
                temp_files=temp_files,
                texture_files=texture_files_for_archive
            )
            
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"Archive created: {archive_path}\n")
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("All processing completed successfully. Now safe to clean temp directory.\n")
        
        # 11. 清理临时文件和temp目录（在所有处理完成后）
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Starting cleanup...\n")
        
        # 清理所有临时文件
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Removed temp file: {f}\n")
                except Exception as e:
                    with open(log_file, "a", encoding="utf-8") as logf:
                        logf.write(f"Failed to remove temp file {f}: {e}\n")
        
        # 彻底清空temp目录
        clean_temp_directory()
        
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write("Cleanup completed.\n")
        
        # 返回结果
        if create_archive and archive_path:
            return archive_path
        else:
            return output_model
    except Exception as e:
        # 异常情况下也要清理
        with open(log_file, "a", encoding="utf-8") as logf:
            logf.write(f"Exception occurred: {e}\n")
            logf.write("Starting emergency cleanup...\n")
        
        # 清理所有临时文件
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        
        # 彻底清空temp目录
        clean_temp_directory()
        
        raise

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
async def test_blender_detection_tool() -> Dict[str, Any]:
    """
    测试Blender 3.6自动检测功能，返回详细的检测结果。
    用于诊断Blender检测问题和验证移植环境。
    
    Returns:
        Dict[str, Any]: 包含系统信息、检测结果和最终路径的详细报告
    """
    return test_blender_detection()

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

def ensure_textures_in_obj_dir(obj_path: str) -> None:
    """
    确保OBJ文件引用的所有贴图都在OBJ文件的同一目录中。
    这对于GLB转换时正确嵌入贴图非常重要。
    Args:
        obj_path (str): OBJ文件路径
    """
    obj_dir = os.path.dirname(obj_path)
    obj_name = os.path.splitext(os.path.basename(obj_path))[0]
    
    # 查找MTL文件
    mtl_path = os.path.join(obj_dir, f"{obj_name}.mtl")
    if not os.path.exists(mtl_path):
        # 尝试查找OBJ文件中引用的MTL文件
        try:
            with open(obj_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.lower().startswith('mtllib'):
                        parts = line.split()
                        if len(parts) > 1:
                            referenced_mtl = parts[1].replace('\\', '/').split('/')[-1]
                            mtl_path = os.path.join(obj_dir, referenced_mtl)
                            break
        except Exception:
            return
    
    if not os.path.exists(mtl_path):
        return
    
    # 读取MTL文件，确保所有贴图都在同一目录
    try:
        with open(mtl_path, 'r', encoding='utf-8') as f:
            mtl_lines = f.readlines()
        
        updated_lines = []
        textures_copied = []
        
        for line in mtl_lines:
            line_lower = line.lower().strip()
            if line_lower.startswith(('map_kd', 'map_ka', 'map_ks', 'map_ns', 'map_bump', 'map_d', 'map_normal', 'map_normalgl', 'map_orm', 'map_roughness', 'map_metallic', 'map_ao', 'map_emissive', 'map_opacity', 'map_displacement', 'map_height')):
                parts = line.split()
                if len(parts) > 1:
                    original_tex_path = parts[-1]
                    tex_filename = original_tex_path.replace('\\', '/').split('/')[-1]
                    target_tex_path = os.path.join(obj_dir, tex_filename)
                    
                    # 如果贴图不在OBJ目录中，尝试从temp目录复制
                    if not os.path.exists(target_tex_path):
                        temp_tex_path = os.path.join(TEMP_DIR, tex_filename)
                        if os.path.exists(temp_tex_path):
                            try:
                                shutil.copy2(temp_tex_path, target_tex_path)
                                textures_copied.append(tex_filename)
                            except Exception:
                                pass
                    
                    # 更新MTL文件中的贴图路径为相对路径
                    if os.path.exists(target_tex_path):
                        # 重写这一行，使用相对路径
                        map_type = parts[0]
                        updated_lines.append(f"{map_type} {tex_filename}\n")
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
        
        # 如果有贴图被复制，更新MTL文件
        if textures_copied:
            with open(mtl_path, 'w', encoding='utf-8') as f:
                f.writelines(updated_lines)
                
    except Exception:
        pass

def collect_texture_files_from_directory(directory: str, collected_files: list = None) -> list:
    """
    从指定目录收集所有贴图文件。
    Args:
        directory (str): 要搜索的目录路径
        collected_files (list): 已收集的文件列表，用于去重
    Returns:
        list: 贴图文件路径列表
    """
    if collected_files is None:
        collected_files = []
    
    texture_files = []
    
    if not os.path.exists(directory) or not os.path.isdir(directory):
        return texture_files
    
    try:
        for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            if os.path.isfile(file_path) and is_texture_file(filename):
                # 避免重复收集同名文件
                if file_path not in collected_files:
                    texture_files.append(file_path)
                    collected_files.append(file_path)
    except Exception:
        pass
    
    return texture_files

def collect_all_texture_files(input_model: str, additional_files: list = None) -> list:
    """
    从输入模型和相关目录收集所有贴图文件。
    Args:
        input_model (str): 输入模型路径
        additional_files (list): 额外文件列表
    Returns:
        list: 所有贴图文件路径列表
    """
    all_texture_files = []
    collected_paths = []  # 用于去重
    
    # 1. 从输入模型目录收集贴图
    if os.path.isdir(input_model):
        # 输入是文件夹
        texture_files = collect_texture_files_from_directory(input_model, collected_paths)
        all_texture_files.extend(texture_files)
    elif os.path.isfile(input_model) and not is_url(input_model):
        # 输入是本地文件
        input_dir = os.path.dirname(input_model)
        texture_files = collect_texture_files_from_directory(input_dir, collected_paths)
        all_texture_files.extend(texture_files)
    
    # 2. 从additional_files中收集贴图
    if additional_files:
        for file_path in additional_files:
            if os.path.isfile(file_path) and is_texture_file(os.path.basename(file_path)):
                if file_path not in collected_paths:
                    all_texture_files.append(file_path)
                    collected_paths.append(file_path)
    
    # 3. 从temp目录收集贴图（处理过程中复制的文件）
    if os.path.exists(TEMP_DIR):
        texture_files = collect_texture_files_from_directory(TEMP_DIR, collected_paths)
        all_texture_files.extend(texture_files)
    
    return all_texture_files

def collect_texture_files(model_dir: str, model_name: str, input_path: str = None) -> list:
    """
    收集模型相关的贴图文件，支持GLB文件的贴图提取。
    Args:
        model_dir (str): 模型所在目录
        model_name (str): 模型文件名（不含扩展名）
        input_path (str): 原始输入文件路径（用于GLB贴图提取）
    Returns:
        list: 贴图文件路径列表
    """
    texture_files = []
    
    # 如果输入是GLB文件，尝试提取嵌入的贴图
    if input_path and input_path.lower().endswith('.glb'):
        try:
            # 创建临时OBJ文件用于贴图提取
            temp_obj = get_temp_file('.obj')
            extracted_textures = glb_to_obj_with_textures(input_path, temp_obj)
            
            # 将提取的贴图复制到模型目录
            for texture_path in extracted_textures:
                if os.path.exists(texture_path):
                    texture_name = os.path.basename(texture_path)
                    dest_path = os.path.join(model_dir, texture_name)
                    try:
                        shutil.copy2(texture_path, dest_path)
                        texture_files.append(dest_path)
                        # 记录到日志文件而不是控制台
                        pass
                    except Exception as e:
                        # 记录到日志文件而不是控制台
                        pass
            
            # 清理临时文件
            try:
                if os.path.exists(temp_obj):
                    os.remove(temp_obj)
                # 清理临时MTL文件
                temp_mtl = temp_obj.replace('.obj', '.mtl')
                if os.path.exists(temp_mtl):
                    os.remove(temp_mtl)
            except Exception:
                pass
                
        except Exception as e:
            # 记录到日志文件而不是控制台
            pass
    
    # 在模型目录中搜索贴图文件
    if os.path.exists(model_dir):
        for filename in os.listdir(model_dir):
            file_path = os.path.join(model_dir, filename)
            if os.path.isfile(file_path) and enhanced_is_texture_file(filename):
                # 检查是否与模型相关（文件名匹配或通用贴图）
                lower_filename = filename.lower()
                lower_model_name = model_name.lower()
                
                # 直接匹配模型名称或包含通用贴图关键词
                if (lower_model_name in lower_filename or 
                    any(keyword in lower_filename for keyword in [
                        'diffuse', 'albedo', 'basecolor', 'base_color', 'color',
                        'normal', 'bump', 'roughness', 'metallic', 'specular',
                        'ambient', 'ao', 'emission', 'opacity', 'alpha',
                        'material', 'texture', 'tex', 'map'
                    ])):
                    texture_files.append(file_path)
    
    # 在父目录中搜索相关贴图
    parent_dir = os.path.dirname(model_dir) if model_dir != os.path.dirname(model_dir) else model_dir
    if os.path.exists(parent_dir) and parent_dir != model_dir:
        for filename in os.listdir(parent_dir):
            file_path = os.path.join(parent_dir, filename)
            if os.path.isfile(file_path) and enhanced_is_texture_file(filename):
                lower_filename = filename.lower()
                lower_model_name = model_name.lower()
                
                # 只收集明确与模型名称匹配的贴图
                if lower_model_name in lower_filename:
                    texture_files.append(file_path)
    
    # 去重并返回
    unique_textures = []
    seen_names = set()
    for texture_path in texture_files:
        texture_name = os.path.basename(texture_path).lower()
        if texture_name not in seen_names:
            unique_textures.append(texture_path)
            seen_names.add(texture_name)
    
    return unique_textures



if __name__ == "__main__":
    mcp.run(transport='stdio')