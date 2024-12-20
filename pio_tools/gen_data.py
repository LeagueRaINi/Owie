Import("env")
import os
import subprocess

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from SCons.Script import COMMAND_LINE_TARGETS

if "idedata" in COMMAND_LINE_TARGETS:
    env.Exit(0)


def read_and_maybe_minify_file(fullPath, minify_path='./node_modules/minify/bin/minify.js'):
    if not os.path.splitext(fullPath)[1].lower() in ['.html', '.js', '.css']:
        with open(fullPath, "rb") as f:
            return f.read()
            
    try:
        original_size = os.path.getsize(fullPath)
        result = subprocess.run(
            ['node', minify_path, fullPath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"Warning: Minification failed for {fullPath}, using original file")
            with open(fullPath, "rb") as f:
                return f.read()
        
        minified = result.stdout
        reduction = ((original_size - len(minified)) / original_size * 100)
        
        if len(minified) < original_size:
            print(f"Minified '{os.path.basename(fullPath)}' from {original_size:,} to {len(minified):,} bytes (-{reduction:.1f}%)")
            return minified
        else:
            print(f"Note: Minification didn't reduce size of {os.path.basename(fullPath)}, using original")
            with open(fullPath, "rb") as f:
                return f.read()
                
    except subprocess.TimeoutExpired:
        print(f"Warning: Minification timeout for {fullPath}, using original file")
        with open(fullPath, "rb") as f:
            return f.read()
    except Exception as e:
        print(f"Warning: Error processing {fullPath}: {str(e)}, using original file")
        with open(fullPath, "rb") as f:
            return f.read()

def collect_files_recursively(directory):
    files = []
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, directory)
            files.append((rel_path, abs_path))
    return sorted(files)

def filename_to_variable_name(filename):
    return filename.upper().replace(".", "_")

def format_size(size_in_bytes):
    mb = size_in_bytes / (1024 * 1024)
    if mb >= 0.01:
        return f"{size_in_bytes:,} bytes ({mb:.2f} MB)"
    return f"{size_in_bytes:,} bytes"

def process_file(file_tuple):
    rel_path, abs_path = file_tuple
    content = read_and_maybe_minify_file(abs_path)
    original_size = os.path.getsize(abs_path)
    minified_size = len(content)
    return (rel_path, content, original_size, minified_size)

def generate_data():
    dataDir = os.path.join(env["PROJECT_DIR"], "data")
    print("dataDir = %s" % dataDir)
    genDir = os.path.join(env.subst("$BUILD_DIR"), 'inline_data')
    print("genDir = %s" % genDir)
    
    if not os.path.exists(dataDir):
        return
    if not os.path.exists(genDir):
        os.makedirs(genDir)
    env.Append(CPPPATH=[genDir])

    files = collect_files_recursively(dataDir)
    
    max_workers = min(32, (os.cpu_count() or 1) * 2)
    print(f"Processing files using {max_workers} threads...")
    
    total_original_size = 0
    total_minified_size = 0
    print_lock = Lock()
    
    results = []
    
    def process_file(file_tuple):
        rel_path, abs_path = file_tuple
        content = read_and_maybe_minify_file(abs_path)
        original_size = os.path.getsize(abs_path)
        minified_size = len(content)
        return (rel_path, content, original_size, minified_size)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_file, files))
    
    out = "// WARNING: Autogenerated by pio_tools/gen_data.py, don't edit manually.\n"
    out += "#ifndef OWIE_GENERATED_DATA_H\n"
    out += "#define OWIE_GENERATED_DATA_H\n\n"
    for rel_path, content, original_size, minified_size in results:
        varName = filename_to_variable_name(os.path.basename(rel_path))
        sizeName = varName + "_SIZE"
        storageArrayName = varName + "_PROGMEM_ARRAY"
        
        total_original_size += original_size
        total_minified_size += minified_size
        
        reduction = ((original_size - minified_size) / original_size * 100) if original_size > 0 else 0
        
        out += f"// From: {rel_path}\n"
        out += f"// Original: {format_size(original_size)}\n"
        out += f"// Minified: {format_size(minified_size)}"
        if minified_size != original_size:
            out += f" (reduced by {reduction:.1f}%)"
        out += "\n"
        
        out += "static const unsigned char %s[] PROGMEM = {\n  " % storageArrayName
        
        firstByte = True
        column = 0
        
        for b in content:
            if not firstByte:
                out += ","
            else:
                firstByte = False
            column = column + 1
            if column > 20:
                column = 0
                out += "\n  "
            out += str(b)
        
        out += "};\n"
        out += "#define %s FPSTR(%s)\n" % (varName, storageArrayName)
        out += "#define %s sizeof(%s)\n\n" % (sizeName, storageArrayName)
    
    # Add total size comments at the end
    total_reduction = ((total_original_size - total_minified_size) / total_original_size * 100) if total_original_size > 0 else 0
    out += f"// Total original size: {format_size(total_original_size)}\n"
    out += f"// Total minified size: {format_size(total_minified_size)}"
    if total_minified_size != total_original_size:
        out += f" (reduced by {total_reduction:.1f}%)"
    out += "\n\n"
    
    out += "#endif // OWIE_GENERATED_DATA_H\n"
    
    with open(os.path.join(genDir, "data.h"), 'w') as f:
        f.write(out)
    
    print(f"\nSummary:")
    print(f"Processed {len(files)} files")
    print(f"Total original size: {format_size(total_original_size)}")
    print(f"Total minified size: {format_size(total_minified_size)}")
    if total_minified_size != total_original_size:
        print(f"Total reduction: {total_reduction:.1f}%")
    print("")

generate_data()
