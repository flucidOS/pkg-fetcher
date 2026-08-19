import re
import json

file_path = 'pkg-branch.json'

with open(file_path, 'r') as f:
    data = f.read()

# 1. Fix the missing closing quote for wpa-supplicant
data = data.replace('"networking/networking-progra\n', '"networking/networking-programs"\n')

# 2. Add the missing comma for the unifdef repository
data = data.replace('"repo": "https://github.com/fanf2/unifdef.git"\n', '"repo": "https://github.com/fanf2/unifdef.git",\n')

# 3. Fix the category typos (general-lib -> general-libs)
data = data.replace('"general-lib"', '"general-libs"')

# 4. Remove all illegal trailing commas right before closing braces
data = re.sub(r',(\s*\})', r'\1', data)

# 5. Fix the missing root closing brace dynamically
data = data.strip()
try:
    json.loads(data)
except json.JSONDecodeError:
    if data.endswith('}'):
        test_data = data + '\n}'
        try:
            json.loads(test_data)
            data = test_data
        except json.JSONDecodeError:
            pass

# Write the fixed data back to the file
with open(file_path, 'w') as f:
    f.write(data)

# Final Verification
try:
    json.loads(data)
    print("Success: JSON syntax is now completely valid! URLs were not modified.")
except json.JSONDecodeError as e:
    print(f"Error: JSON is still invalid at {e}")
