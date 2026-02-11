
import unittest
import os
import re
import string
import secrets
from datetime import datetime
import shutil
import tempfile
from pathlib import Path

# 模拟 train_online.py 中的命名逻辑，稍后会集成进去
def generate_model_name(folder_name, user_model_name, existing_files=None):
    if existing_files is None:
        existing_files = []
        
    # 1. Folder name
    folder = folder_name
    
    # 2. Clean model name
    # Keep only letters, numbers, underscore
    clean_model = re.sub(r'[^a-zA-Z0-9_]', '', user_model_name)
    if not clean_model:
        clean_model = "model" # Fallback if empty after cleaning
        
    # 3. Date
    date_str = datetime.now().strftime("%y%m%d")
    
    # 4. Generate unique name
    while True:
        # Cryptographically secure random string
        chars = string.ascii_uppercase + string.digits
        rand_suffix = ''.join(secrets.choice(chars) for _ in range(4))
        
        name = f"{folder}-{clean_model}-{date_str}-{rand_suffix}"
        
        # Check uniqueness
        # We simulate file check by looking at existing_files list
        # In real code this would check os.path.exists
        is_conflict = False
        for f in existing_files:
            if f == name or f == f"{name}.tflite":
                is_conflict = True
                break
        
        if not is_conflict:
            return name

class TestModelNaming(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cwd_patch = os.getcwd()
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_format_compliance(self):
        """验证生成的名称符合 folder-model-YYMMDD-ABCD 格式"""
        folder = "myproject"
        model = "pilot"
        name = generate_model_name(folder, model)
        
        # Split parts
        parts = name.split('-')
        self.assertEqual(len(parts), 4)
        
        self.assertEqual(parts[0], folder)
        self.assertEqual(parts[1], model)
        self.assertTrue(re.match(r'^\d{6}$', parts[2])) # Date
        self.assertTrue(re.match(r'^[A-Z0-9]{4}$', parts[3])) # Random suffix

    def test_model_name_cleaning(self):
        """验证非法字符过滤"""
        folder = "proj"
        # Input with spaces, dashes, special chars
        dirty_name = "super-cool_model@v1.0" 
        # Expected: supercool_modelv10 (removed - @ .)
        # Actually our regex removes - as well.
        
        name = generate_model_name(folder, dirty_name)
        parts = name.split('-')
        cleaned_model = parts[1]
        
        self.assertTrue(re.match(r'^[a-zA-Z0-9_]+$', cleaned_model))
        self.assertNotIn('@', cleaned_model)
        self.assertNotIn('-', cleaned_model)
        self.assertNotIn('.', cleaned_model)

    def test_empty_model_name_fallback(self):
        """验证空模型名回退"""
        folder = "proj"
        name = generate_model_name(folder, "!!!") # becomes empty string
        parts = name.split('-')
        self.assertEqual(parts[1], "model")

    def test_collision_resolution(self):
        """验证冲突时重新生成"""
        folder = "proj"
        model = "pilot"
        
        # Mock existing files to force collision
        # We need to predict what the first random seed might be? 
        # Impossible with secrets.choice.
        # Instead, we generate one, add it to existing, and request again.
        
        # First generation
        name1 = generate_model_name(folder, model)
        
        # Second generation with name1 existing
        existing = [f"{name1}.tflite"]
        name2 = generate_model_name(folder, model, existing)
        
        self.assertNotEqual(name1, name2)
        # Verify base parts are same
        self.assertEqual(name1.rsplit('-', 1)[0], name2.rsplit('-', 1)[0])

    def test_concurrency_simulation(self):
        """模拟10000次生成，验证生成的唯一性"""
        folder = "bench"
        model = "test"
        existing = set()
        
        count = 10000
        collisions = 0
        
        for _ in range(count):
            # For this test, we pass the SET of existing names to the function
            # But our function takes a list/iterable.
            # To simulate "check filesystem", we just check against our set inside the function logic
            # implemented in generate_model_name.
            
            # However, generate_model_name is designed to generate ONE unique name against existing.
            # So we add the result to existing.
            
            name = generate_model_name(folder, model, existing)
            
            # Since generate_model_name guarantees uniqueness against 'existing',
            # we just need to ensure it's successfully added.
            if name in existing:
                self.fail(f"Generated duplicate name: {name}")
            
            existing.add(name)
            
        self.assertEqual(len(existing), count)
        print(f"\nGenerated {count} unique names successfully.")

if __name__ == '__main__':
    unittest.main()
