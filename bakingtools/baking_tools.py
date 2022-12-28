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
import caching_utilities as cache

class Baking_Pass_Info():

    image_settings = None
    texture_node_color_space = None

    def __init__(self, name, enabled, suffix, color_depth):
        self.name = name
        self.enabled = enabled
        self.suffix = suffix
        self.color_depth = color_depth

class OBJECT_OT_BatchBake(bpy.types.Operator):
    """Batch bake textures"""
    bl_label = "BatchBake"
    bl_idname = "object.batch_baker"
    bl_description = "Batch bakes textures"

    bakeable_types = ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME')

    # TODO leverage Blender's built-in tools for this instead
    file_formats_to_extensions = {'BMP'                 : '.bmp',
                                  'PNG'                 : '.png',
                                  'JPEG'                : '.jpg',
                                  'TARGA'               : '.tga',
                                  'TARGA_RAW'           : '.tga',
                                  'OPEN_EXR_MULTILAYER' : '.exr',
                                  'OPEN_EXR'            : '.exr',
                                  'HDR'                 : '.hdr',
                                  'TIFF'                : '.tif'}

    def execute(self, context):
        self.settings = context.scene.baking_tools_settings

        # Cache the original render settings and cycles settings so they can be restored later
        render_settings_original = cache.CachedProperties(object_to_cache = context.scene.render)
        cycles_settings_original = cache.CachedProperties(object_to_cache = context.scene.cycles)
        display_device_original = context.scene.display_settings.display_device

        self.get_baking_pass_info()

        # Set up the image settings that will be used for each baking pass
        try:
            self.setup_image_settings()
        except KeyError as e:
            print(repr(e))
            return {'CANCELLED'}

        active = context.active_object
        if active.type not in self.bakeable_types:
            return {'CANCELLED'}

        self.cached_material_output_links = {} # Keep track of all of the original node connections in a dictionary

        material_to_bake = active.data.materials[0] # TODO make this work for multi-material setups
        self.cache_material_output_link(material_to_bake)

        # Set up the render settings and cycles settings for baking
        render_settings_bake = cache.CachedProperties(cache_to_copy = render_settings_original, dont_assign_values=True)
        render_settings_bake.set_property("engine", 'CYCLES')
        render_settings_bake.set_property("use_file_extension", True)

        cycles_settings_bake = cache.CachedProperties(cache_to_copy = cycles_settings_original, dont_assign_values=True)
        cycles_settings_bake.set_property("device", 'GPU')
        cycles_settings_bake.set_property("use_adaptive_sampling", False)
        cycles_settings_bake.set_property("samples", 16) # TODO figure out how many baking samples we need 1? 16? User selectable?
        cycles_settings_bake.set_property("use_denoising", False)

        # Apply the render setting and cycles settings for the bake
        render_settings_bake.apply_properties_to_object(context.scene.render)
        cycles_settings_bake.apply_properties_to_object(context.scene.cycles)

        # BAKING TIME!!!
        self.nodes_to_delete_during_cleanup = []
        for baking_pass in self.baking_passes.values():
            if not baking_pass.enabled:
                continue

            self.initialize_baker_texture(baking_pass)
            self.create_baking_image_texture_node(material_to_bake, baking_pass)

            # Normal will use the normal bake setting and the default connection, emission will use the default connection # TODO, handle this better
            if baking_pass.name not in ["Normal", "Emission"]:
                self.hook_up_node_for_bake(material_to_bake, baking_pass)

            baking_pass.image_settings.apply_properties_to_object(context.scene.render.bake.image_settings) # Apply the settings so that the bake happens with the correct settings
            baking_pass.image_settings.apply_properties_to_object(context.scene.render.image_settings) # Apply the settings so that the texture output happens with the correct settings
            
            # Perform the bake
            if baking_pass.name == "Normal":
                context.scene.display_settings.display_device = 'XYZ'
                bpy.ops.object.bake(type = 'NORMAL', margin = 0, use_selected_to_active = False, use_clear = False)
            elif baking_pass.name == "Base Color":
                context.scene.display_settings.display_device = 'sRGB'
                bpy.ops.object.bake(type = 'EMIT', margin = 0, use_selected_to_active = False, use_clear = False)
            else:
                context.scene.display_settings.display_device = 'XYZ'
                bpy.ops.object.bake(type = 'EMIT', margin = 0, use_selected_to_active = False, use_clear = False)

            # Build the file name for output
            output_file = bpy.path.abspath(self.settings.export_path) # Get the absolute export path
            output_file += self.settings.texture_set_name # Add the texture set name

            suffix = baking_pass.suffix

            output_file += suffix
            texture_format = bpy.context.scene.render.bake.image_settings.file_format
            extension = self.file_formats_to_extensions[texture_format] # Get the file extension
            output_file += extension # Add the file extension

            self.settings.baker_texture.save_render(filepath= output_file)

            # Clean up
            for node in self.nodes_to_delete_during_cleanup:
                material_to_bake.node_tree.nodes.remove(node) # Remove the node
            self.nodes_to_delete_during_cleanup.clear()

            try:
                self.cached_material_output_links[material_to_bake].apply_link_to_node_tree(material_to_bake.node_tree) # Hook up the original node to the output
            except cache.LinkFailedError as error:
                self.report({"WARNING"}, error.message)
                return

        # Set the render setting and cycles settings back to their original values
        render_settings_original.apply_properties_to_object(context.scene.render)
        cycles_settings_original.apply_properties_to_object(context.scene.cycles)
        context.scene.display_settings.display_device = display_device_original

        return {'FINISHED'}

    def get_baking_pass_info(self):
        self.baking_passes = {}
        self.baking_passes["Base Color"] = Baking_Pass_Info(name="Base Color", enabled=self.settings.baking_pass_basecolor, suffix=self.settings.suffix_basecolor, color_depth='8')
        self.baking_passes["Roughness"]  = Baking_Pass_Info(name="Roughness",  enabled=self.settings.baking_pass_roughness, suffix=self.settings.suffix_roughness, color_depth='8')
        self.baking_passes["Metallic"]   = Baking_Pass_Info(name="Metallic",   enabled=self.settings.baking_pass_metalness, suffix=self.settings.suffix_metalness, color_depth='8')
        self.baking_passes["Normal"]     = Baking_Pass_Info(name="Normal",     enabled=self.settings.baking_pass_normal,    suffix=self.settings.suffix_normal,    color_depth='16')
        self.baking_passes["Emission"]   = Baking_Pass_Info(name="Emission",   enabled=self.settings.baking_pass_emission,  suffix=self.settings.suffix_emission,  color_depth='8')

    def cache_material_output_link(self, material):
        """Cache the original link to the output node so it can be recovered later"""
        # TODO make this support all outputs (Surface, Volume, Displacement), not just the Surface output
        # TODO make sure this handles with there is nothing hooked up to the output node

        node_output = material.node_tree.nodes["Material Output"] # Get the output node
        original_link = cache.CachedNodeLink(node_output.inputs[0].links[0]) # Cache the details of the link to the output node
        self.cached_material_output_links[material] = original_link

    def hook_up_node_for_bake(self, material, baking_pass):
        # material.use_nodes = True # TODO clean this up

        node_output = material.node_tree.nodes["Material Output"] # Get the existing output node
        connected_node_name = node_output.inputs[0].links[0].from_node.name # Name of the node on the left side that is outputting the link
        if connected_node_name != "Principled BSDF":
            print("This node is not supported") # TODO support more nodes
        node_shader = material.node_tree.nodes[connected_node_name]

        node_emission = material.node_tree.nodes.new('ShaderNodeEmission')
        self.nodes_to_delete_during_cleanup.append(node_emission)
        material.node_tree.links.new(node_output.inputs[0], node_emission.outputs['Emission']) # Hook up the emission node to the surface output

        if len(node_shader.inputs[baking_pass.name].links):
            input_node_name = node_shader.inputs[baking_pass.name].links[0].from_node.name
            input_socket_name = node_shader.inputs[baking_pass.name].links[0].from_socket.name
            node_input = material.node_tree.nodes[input_node_name]
            material.node_tree.links.new(node_emission.inputs[0], node_input.outputs[input_socket_name])
        else:
            input_type = node_emission.inputs[0].type
            if input_type == 'RGBA': # TODO figure out why this was causing problems
                # node_emission.inputs[0].default_value = node_shader.inputs[baking_pass.name].default_value
                return
            elif input_type == 'VALUE':
                node_value = material.node_tree.nodes.new('ShaderNodeValue')
                self.nodes_to_delete_during_cleanup.append(node_value)
                node_value.outputs[0].default_value = node_shader.inputs[baking_pass.name].default_value
                material.node_tree.links.new(node_emission.inputs[0], node_value.outputs[0])
            elif input_type == 'VECTOR':
                print("Please handle other types as well") # TODO
            else:
                print("Please handle other types as well") # TODO

    def setup_image_settings(self):

            # Create the core image settings that are common for all types of baking
            # Original image settings don't need to be cached here because they are already part of the cached RenderSettings
            common_settings = cache.CachedProperties(object_to_cache = bpy.context.scene.render.bake.image_settings, dont_assign_values=True)
            common_settings.set_property("color_management", 'OVERRIDE')
            common_settings.set_property("color_mode", 'RGB')
            common_settings.set_property("tiff_codec", 'DEFLATE')
            common_settings.set_property("view_settings.look", 'None')
            common_settings.set_property("view_settings.use_curve_mapping", False)
            common_settings.set_property("view_settings.view_transform", 'Raw')

            # Create image settings for each of the baking passes
            for baking_pass in self.baking_passes.values():
                baking_pass.image_settings = cache.CachedProperties(cache_to_copy = common_settings)

            # bitdepth_8_format = 'TARGA'
            bitdepth_8_format = 'PNG'
            bitdepth_16_format = 'TIFF'

            # Setup the appropriate output settings for basecolor
            baking_pass = self.baking_passes["Base Color"]
            x = baking_pass.image_settings
            x.set_property("file_format", bitdepth_8_format)
            x.set_property("color_depth", baking_pass.color_depth)
            x.set_property("linear_colorspace_settings.is_data", False)
            x.set_property("linear_colorspace_settings.name", 'sRGB')
            baking_pass.texture_node_color_space = 'sRGB'

            # Setup the appropriate output settings for roughness
            baking_pass = self.baking_passes["Roughness"]
            x = baking_pass.image_settings
            x.set_property("file_format", bitdepth_8_format)
            x.set_property("color_depth", baking_pass.color_depth)
            x.set_property("linear_colorspace_settings.is_data", True)
            x.set_property("linear_colorspace_settings.name", 'Raw')
            baking_pass.texture_node_color_space = 'Non-Color'

            # Setup the appropriate output settings for metalness
            baking_pass = self.baking_passes["Metallic"]
            x = baking_pass.image_settings
            x.set_property("file_format", bitdepth_8_format)
            x.set_property("color_depth", baking_pass.color_depth)
            x.set_property("linear_colorspace_settings.is_data", True)
            x.set_property("linear_colorspace_settings.name", 'Raw')
            baking_pass.texture_node_color_space = 'Non-Color'

            # Setup the appropriate output settings for normal
            baking_pass = self.baking_passes["Normal"]
            x = baking_pass.image_settings
            x.set_property("file_format", bitdepth_16_format)
            x.set_property("color_depth", baking_pass.color_depth)
            x.set_property("linear_colorspace_settings.is_data", True)
            x.set_property("linear_colorspace_settings.name", 'Raw')
            baking_pass.texture_node_color_space = 'Non-Color'

            # Setup the appropriate output settings for emission
            baking_pass = self.baking_passes["Emission"]
            x = baking_pass.image_settings
            x.set_property("file_format", bitdepth_8_format)
            x.set_property("color_depth", baking_pass.color_depth)
            x.set_property("linear_colorspace_settings.is_data", False)
            x.set_property("linear_colorspace_settings.name", 'sRGB')
            baking_pass.texture_node_color_space = 'Non-Color'

    def initialize_baker_texture(self, baking_pass):
        suffix = baking_pass.suffix
        new_texture = "_".join([self.settings.texture_set_name, suffix])

        # Remove the texture if it already exists so that it can be reinitialized with the correct resolution and settings
        image = bpy.data.images.get(new_texture, None)
        if image: bpy.data.images.remove(image, do_unlink = True)

        # Create the new texture
        use_float = baking_pass.color_depth != '8' # We only need full float for color depths higher than 8
        bpy.data.images.new(name = new_texture, width = self.settings.texture_size, height = self.settings.texture_size, float_buffer = use_float)

        # Save the new texture in a variable where we can reference it later
        self.settings.baker_texture = bpy.data.images.get(new_texture, None)

    def create_baking_image_texture_node(self, material, baking_pass):
        self.baked_image_node = material.node_tree.nodes.new('ShaderNodeTexImage')
        self.nodes_to_delete_during_cleanup.append(self.baked_image_node)
        self.baked_image_node.location = [0, 0]
        self.baked_image_node.label = 'BakerTexture'
        self.baked_image_node.name = 'BakerTexture'
        self.baked_image_node.image = self.settings.baker_texture
        self.baked_image_node.image.colorspace_settings.name = baking_pass.texture_node_color_space
        self.baked_image_node.select = True # Make the node the active selection so that it will receive the bake.
        material.node_tree.nodes.active = self.baked_image_node # Make the new node the active node so that it will receive the bake.

class BakingTools_Props(bpy.types.PropertyGroup):
    """Properties to for baking"""
    texture_set_name : bpy.props.StringProperty(name = "Texture Set name", default = "BakedTexture", subtype='FILE_NAME')
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

    export_path : bpy.props.StringProperty(name = "Output Path", subtype='DIR_PATH')

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
        row.prop(settings, 'export_path')

        row = layout.row()
        row.prop(settings, 'texture_set_name')

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