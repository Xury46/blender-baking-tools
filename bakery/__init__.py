bl_info = {
    "name" : "bakery",
    "author" : "Xury Greer",
    "version" : (0, 1),
    "blender" : (3, 4, 1),
    "location" : "Properties > Render > Baking Tools",
    "warning" : "",
    "wiki_url" : "",
    "category" : "Render",
}

# Import local modules
# More info: https://archive.blender.org/wiki/index.php/Dev:Py/Scripts/Cookbook/Code_snippets/Multi-File_packages/
if "bpy" in locals():
	import imp
	imp.reload(baking_tools)

else:
	from . import baking_tools

def register():
    baking_tools.register()

def unregister():
    baking_tools.unregister()

if __name__ == "__main__":
    register()