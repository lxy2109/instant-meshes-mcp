# instant-meshes-mcp

本项目用于通过命令行和API接口，基于Instant Meshes对3D模型（OBJ/GLB）进行自动重拓扑和简化，支持批量处理、URL输入、材质贴图保留等功能。

## 功能简介
- 支持GLB/OBJ模型的重拓扑与简化
- 自动处理远程URL和本地文件
- 保留和修复OBJ材质与贴图
- 输出标准GLB格式，便于后续3D应用
- 日志记录与临时文件自动清理

## 依赖环境
- Python 3.8+
- Windows 10/11
- 需放置`Instant Meshes.exe`于项目根目录

## 安装依赖
```bash
pip install -r requirements.txt
```

## 使用方法
1. 启动服务：
```bash
python server.py
```
2. 通过API或命令行调用`remesh_model`工具，传入模型路径、目标面数等参数。

## 通过 MCP 调用

本项目已集成为 MCP 服务（instant-meshes-mcp），可通过 MCP 客户端或其他支持 MCP 协议的平台进行调用。

### 1. 启动 MCP 服务

```bash
python server.py
```

或通过 MCP 管理器自动启动（如已配置在 mcp.json）。

### 2. 通过 MCP 客户端调用

以 JSON-RPC 或 MCP 工具链为例，调用 `remesh_model`：

```json
{
  "method": "remesh_model",
  "params": {
    "input_model": "your_model.glb",
    "target_faces": 5000
  }
}
```

返回值为输出模型的路径（GLB 格式）。

### 3. mcp.json 配置示例

已在 mcp.json 中配置如下：

```json
"instant-meshes-mcp": {
  "command": "python",
  "args": [
    "your_abs_dir/instant-meshes-mcp/server.py"
  ],
  "env": {
    "PYTHONUNBUFFERED": "1"
  }
}
```

## 主要依赖包
- trimesh：3D模型格式转换
- pymeshlab：网格简化
- requests：远程文件下载
- psutil：进程管理

## 目录结构
- `server.py`：主服务与API实现
- `Instant Meshes.exe`：重拓扑核心程序
- `output_remesh/`：输出模型目录
- `temp/`：临时文件目录
- `logs/`：运行日志

## 注意事项
- 仅支持Windows平台
- 输入模型建议为OBJ或GLB格式
- 输出模型统一为GLB格式，保留贴图

## 示例
```python
from server import remesh_model
output = await remesh_model('input.glb', target_faces=5000)
print('输出模型路径:', output)
``` 