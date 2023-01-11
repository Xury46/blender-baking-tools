bl_info = {
    "name" : "baking tools",
    "author" : "Xury Greer",
    "version" : (0, 1),
    "blender" : (3, 4, 1),
    "location" : "View3d > Baking Tools",
    "warning" : "",
    "wiki_url" : "",
    "category" : "Render",
}

import bpy
from caching_utilities import CachedProperties
from caching_utilities import CachedNodeLink

class OBJECT_OT_BatchBake(bpy.types.Operator):
    """Batch bake textures"""
    bl_label = "BatchBake"
    bl_idname = "object.batch_baker"
    bl_description = "Batch bakes textures"

    bakeable_types = ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME')

    def execute(self, context):
        self.settings = context.scene.baking_tools_settings

        active = context.active_object
        if active.type not in self.bakeable_types:
            return {'CANCELLED'}

        # Set up the image settings that will be used for each baking pass
        self.image_settings = {}
        try:
            self.setup_image_settings()
        except KeyError as e:
            print(repr(e))
            return {'CANCELLED'}

        self.initialize_baker_texture()
        self.create_baking_image_texture_node(active.data.materials[0])

    # def cache_material_output_link(self, material):
    #     """Cache the original link to the output node so it can be recovered later"""
    #     # TODO make this support all outputs (Surface, Volume, Displacement), not just the Surface output
    #     # TODO make sure this handles with there is nothing hooked up to the output node

    #     node_output = material.node_tree.nodes["Material Output"] # Get the output node
    #     original_link = cache.CachedNodeLink(node_output.inputs[0].links[0]) # Cache the details of the link to the output node
    #     self.cached_material_output_links[material] = original_link

    # def create_blank_material(self, material_name):
    #     new_material = bpy.data.materials.new(name = material_name)
    #     new_material.use_nodes = True
    #     node_output = new_material.node_tree.nodes["Material Output"] # Get the output node

    #     # Delete all of the old nodes (other than the output node)
    #     for node in new_material.node_tree.nodes:
    #         if node != node_output:
    #             new_material.node_tree.nodes.remove(node)

    #     return new_material

    # def add_id_nodes_to_material(self, material_to_modify, index, total_num_ids):
    #     """Modify material to add random id colors"""
    #     material_to_modify.use_nodes = True

    #     node_output = material_to_modify.node_tree.nodes["Material Output"] # Get the existing output node

    #     # Create an instance of the ID Color node group
    #     node_id_color = material_to_modify.node_tree.nodes.new('ShaderNodeGroup')
    #     node_id_color.node_tree = bpy.data.node_groups[ID_NODE_GROUP_NAME]
    #     node_id_color.name = "Color ID Group"
    #     node_id_color.location = [130, 300]
    #     node_id_color.inputs['Index'].default_value = index
    #     node_id_color.inputs['Total'].default_value = total_num_ids

        # Cache the original render settings and cycles settings so they can be restored later
        render_settings_original = CachedProperties(object_to_cache = context.scene.render)
        cycles_settings_original = CachedProperties(object_to_cache = context.scene.cycles)
        display_device_original = context.scene.display_settings.display_device

        # Set up the render settings and cycles settings for baking
        render_settings_bake = CachedProperties(cache_to_copy = render_settings_original, dont_assign_values=True)
        render_settings_bake.set_property("engine", 'CYCLES')

        cycles_settings_bake = CachedProperties(cache_to_copy = cycles_settings_original, dont_assign_values=True)
        cycles_settings_bake.set_property("device", 'GPU')
        cycles_settings_bake.set_property("use_adaptive_sampling", False)
        cycles_settings_bake.set_property("samples", 16) # TODO figure out how many baking samples we need 1? 16? User selectable?
        cycles_settings_bake.set_property("use_denoising", False)

        # Apply the render setting and cycles settings for the bake
        render_settings_bake.apply_properties_to_object(context.scene.render)
        cycles_settings_bake.apply_properties_to_object(context.scene.cycles)
        context.scene.display_settings.display_device = 'XYZ'

        # Perform the bake
        bpy.ops.object.bake(type = 'EMIT', margin = 0, use_selected_to_active = False, use_clear = False)

        print("We're doing the bake!")

        # Set the render setting and cycles settings back to their original values
        render_settings_original.apply_properties_to_object(context.scene.render)
        cycles_settings_original.apply_properties_to_object(context.scene.cycles)
        context.scene.display_settings.display_device = display_device_original

        return {'FINISHED'}

    def setup_image_settings(self):

            # Cache the original image settings
            original = self.image_settings["original"] = CachedProperties(object_to_cache = bpy.context.scene.render.bake.image_settings)

            # Create the core image settings that are common for all types of baking
            common_settings = CachedProperties(cache_to_copy = original, dont_assign_values=True)
            common_settings.set_property("color_management", 'OVERRIDE')
            common_settings.set_property("color_mode", 'RGB')
            common_settings.set_property("tiff_codec", 'DEFLATE')
            common_settings.set_property("view_settings.look", 'None')
            common_settings.set_property("view_settings.use_curve_mapping", False)
            common_settings.set_property("view_settings.view_transform", 'Raw')

            # Create image settings for each of the baking passes

            # Setup the appropriate output settings for basecolor
            if self.settings.baking_pass_basecolor:
                x = self.image_settings["basecolor"] = CachedProperties(cache_to_copy = common_settings)
                x.set_property("file_format", 'TARGA')
                x.set_property("color_depth", '8')
                x.set_property("linear_colorspace_settings.is_data", False)
                x.set_property("linear_colorspace_settings.name", 'sRGB')
                # self.node_basecolor.image.save_render(filepath = self.settings.export_path + self.node_basecolor.image.name + ".tga")

            # Setup the appropriate output settings for roughness
            if self.settings.baking_pass_roughness:
                x = self.image_settings["roughness"] = CachedProperties(cache_to_copy = common_settings)
                # TODO

            # Setup the appropriate output settings for metalness
            if self.settings.baking_pass_metalness:
                x = self.image_settings["metalness"] = CachedProperties(cache_to_copy = common_settings)
                # TODO

            # Setup the appropriate output settings for normal
            if self.settings.baking_pass_normal:
                x = self.image_settings["normal"] = CachedProperties(cache_to_copy = common_settings)
                x.set_property("file_format", 'TIFF')
                x.set_property("color_depth", '16')
                x.set_property("linear_colorspace_settings.is_data", True)
                x.set_property("linear_colorspace_settings.name", 'Raw')
                # self.node_normal.image.save_render(filepath = self.settings.export_path + self.node_normal.image.name + ".tif")

            # Setup the appropriate output settings for emission
            if self.settings.baking_pass_emission:
                x = self.image_settings["emission"] = CachedProperties(cache_to_copy = common_settings)
                # TODO
    
    def initialize_baker_texture(self):
        new_texture = self.settings.texture_set_name

        # Remove the texture if it already exists so that it can be reinitialized with the correct resolution and settings
        image = bpy.data.images.get(new_texture, None)
        if image: bpy.data.images.remove(image, do_unlink = True)

        # Create the new texture
        bpy.data.images.new(name = new_texture, width = self.settings.texture_size, height = self.settings.texture_size, float_buffer = True) #TODO float_buffer not needed for RGB

        # Save the new texture in a variable where we can reference it later
        self.settings.baker_texture = bpy.data.images.get(new_texture, None)

    def create_baking_image_texture_node(self, material):
        new_node = material.node_tree.nodes.new('ShaderNodeTexImage')
        new_node.location = [0, 0]
        new_node.label = 'BakerTexture'
        new_node.name = 'BakerTexture'
        new_node.image = self.settings.baker_texture
        new_node.image.colorspace_settings.name = "Non-Color" # TODO make this correct for each pass.
        new_node.select = True # Make the node the active selection so that it will receive the bake.
        material.node_tree.nodes.active = new_node # Make the new node the active node so that it will receive the bake.

class BakingTools_Props(bpy.types.PropertyGroup):
    """Properties to for baking"""
    texture_set_name : bpy.props.StringProperty(name = "Texture Set name", default = "BakedTexture")
    texture_size : bpy.props.IntProperty(name = "Resolution", default = 1024)
    baker_texture : bpy.props.PointerProperty(name = "Texture Image", type = bpy.types.Image)

    # BaseColor
    baking_pass_basecolor : bpy.props.BoolProperty(name = "BaseColor", default = True)
    suffix_basecolor : bpy.props.StringProperty(name = "Suffix", default = "BaseColor")

    # Roughness
    baking_pass_roughness : bpy.props.BoolProperty(name = "Roughness", default = True)
    suffix_roughness : bpy.props.StringProperty(name = "Suffix", default = "Roughness")
    invert_roughness : bpy.props.BoolProperty(name = "Invert Roughness", default = False)

    # Metalness
    baking_pass_metalness : bpy.props.BoolProperty(name = "Metalness", default = True)
    suffix_metalness : bpy.props.StringProperty(name = "Suffix", default = "Metal")

    # Normal
    baking_pass_normal    : bpy.props.BoolProperty(name = "Normal",    default = True)
    suffix_normal : bpy.props.StringProperty(name = "Suffix", default = "Normal")

    # Emission
    baking_pass_emission  : bpy.props.BoolProperty(name = "Emission",  default = True)
    suffix_emission : bpy.props.StringProperty(name = "Suffix", default = "Emit")

class VIEW_3D_PT_BakingTools(bpy.types.Panel):
    """Create a panel UI in Blender's 3D Viewport Sidebar"""
    bl_label = "Baking Tools"
    bl_idname = "VIEW_3D_PT_BAKINGTOOLS"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Baking Tools'

    def draw(self, context):
        settings = context.scene.baking_tools_settings

        layout = self.layout

        # Checkboxes for baking passes
        row = layout.row()
        row.label(text = "Baking Passes:")

        row = layout.row()
        row.prop(settings, 'baking_pass_basecolor')
        row.prop(settings, 'suffix_basecolor')

        row = layout.row()
        row.prop(settings, 'baking_pass_roughness')
        row.prop(settings, 'suffix_roughness')

        row = layout.row()
        row.prop(settings, 'baking_pass_metalness')
        row.prop(settings, 'suffix_metalness')

        row = layout.row()
        row.prop(settings, 'baking_pass_normal')
        row.prop(settings, 'suffix_normal')

        row = layout.row()
        row.prop(settings, 'baking_pass_emission')
        row.prop(settings, 'suffix_emission')

        row = layout.row()
        row.prop(settings, 'texture_size')

        row = layout.row()
        row.operator('object.batch_baker', icon = 'RENDER_STILL')

# Register the add-on in Blender
classes = [BakingTools_Props, OBJECT_OT_BatchBake, VIEW_3D_PT_BakingTools]

def register():
    # Register the classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Create the settings
    bpy.types.Scene.baking_tools_settings = bpy.props.PointerProperty(type = BakingTools_Props)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    # Delete the settings
    del bpy.context.scene.baking_tools_settings

if __name__ == "__main__":
    register()