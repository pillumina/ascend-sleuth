 # Compilation Optimization

Python 3.6+ supports LTO (Link Time Optimization) and PGO (Profile Guided Optimization), which can significantly improve Python runtime performance.

## LTO + PGO Python Installation

```bash
# Download pre-compiled optimized Python 3.11 (Bisheng compiler)
mkdir -p /workspace/tmp
cd /workspace/tmp

wget https://repo.oepkgs.net/ascend/pytorch/vllm/lib/libcrypto.so.1.1
wget https://repo.oepkgs.net/ascend/pytorch/vllm/lib/libomp.so
wget https://repo.oepkgs.net/ascend/pytorch/vllm/lib/libssl.so.1.1
wget https://repo.oepkgs.net/ascend/pytorch/vllm/python/py311_bisheng.tar.gz

# Install
cp ./*.so* /usr/local/lib
tar -zxvf ./py311_bisheng.tar.gz -C /usr/local/
mv /usr/local/py311_bisheng/ /usr/local/python
sed -i "1c#\!/usr/local/python/bin/python3.11" /usr/local/python/bin/pip3
sed -i "1c#\!/usr/local/python/bin/python3.11" /usr/local/python/bin/pip3.11
ln -sf /usr/local/python/bin/python3 /usr/bin/python
ln -sf /usr/local/python/bin/python3 /usr/bin/python3
ln -sf /usr/local/python/bin/python3.11 /usr/bin/python3.11
ln -sf /usr/local/python/bin/pip3 /usr/bin/pip3
ln -sf /usr/local/python/bin/pip3 /usr/bin/pip

export PATH=/usr/bin:/usr/local/python/bin:$PATH
```

## Important Notes

- Compilation optimization must be completed **before** installing vLLM/vllm-ascend
- Otherwise, the binary files will not use the optimized Python
- Expected performance improvement: 5-15% for Python-heavy workloads
