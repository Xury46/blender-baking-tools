bl_info = {
    "name" : "baking tools",
    "author" : "Xury Greer",
    "version" : (0, 1),
    "blender" : (3, 4, 0),
    "location" : "View3d > Baking Tools",
    "warning" : "",
    "wiki_url" : "",
    "category" : "Render",
}

import bpy
from caching_utilites import CachedProperties
from caching_utilites import CachedNodeLink

class OBJECT_OT_BatchBake(bpy.types.Operator):
    """Batch bake textures"""
    bl_label = "BatchBake"
    bl_idname = "object.batch_baker"
    bl_description = "Batch bakes textures"

    def execute(self, context):
        self.settings = context.scene.bake_tools_settings

        active = context.active_object

        rs_original = CachedProperties(bpy.context.scene.render)
        rs_modified = CachedProperties(cache_to_copy = rs_original)
        rs_blank = CachedProperties(cache_to_copy = rs_original, dont_assign_values=True)

        rs_modified.set_property("bake.use_pass_direct", False)
        rs_modified.set_property("bake.use_pass_indirect", False)

        print("ORIGINAL")
        rs_original.print_cached_properties()

        print("MODIFIED")
        rs_modified.print_cached_properties()

        print("BLANK")
        rs_blank.print_cached_properties()

        # print(active.name)

        return {'FINISHED'}

class BakingTools_Props(bpy.types.PropertyGroup):
    """Properties to for baking"""
    # bone_tags : bpy.props.CollectionProperty(type = Bone_Tag_Prop) # A list of strings that can be edited by the user to add more possible tags
    # active_tagged_bone_index : bpy.props.IntProperty() # Keeps track of the active index in the UI list

class VIEW_3D_PT_BakingTools(bpy.types.Panel):
    """Create a panel UI in Blender's 3D Viewport Sidebar"""
    bl_label = "Baking Tools"
    bl_idname = "VIEW_3D_PT_BAKINGTOOLS"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Baking Tools'

    def draw(self, context):
        # settings = context.scene.baking_tools_settings
        # active = context.active_object
        # if active.type != 'ARMATURE':
        #     return

        layout = self.layout
        row = layout.row()
        row.operator('object.batch_baker', icon = 'RENDER_STILL')

# Register the add-on in Blender
classes = [BakingTools_Props, OBJECT_OT_BatchBake, VIEW_3D_PT_BakingTools]

def register():
    # Register the classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Create the settings
    bpy.types.Scene.bake_tools_settings = bpy.props.PointerProperty(type = BakingTools_Props)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    # Delete the settings
    del bpy.context.scene.bake_tools_settings

if __name__ == "__main__":
    register()