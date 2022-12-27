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
from caching_utilities import LinkFailedError

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

        self.cached_material_output_links = {} # Keep track of all of the original node connections in a dictionary

        material_to_bake = active.data.materials[0] # TODO make this work for multi-material setups
        self.cache_material_output_link(material_to_bake)

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

        baking_passes = []
        if self.settings.baking_pass_basecolor:
            baking_passes.append("Base Color")
        if self.settings.baking_pass_roughness:
            baking_passes.append("Roughness")
        if self.settings.baking_pass_metalness:
            baking_passes.append("Metallic")
        if self.settings.baking_pass_normal:
            baking_passes.append("Normal")
        if self.settings.baking_pass_emission:
            baking_passes.append("Emission")

# <bpy_struct, NodeSocketColor("Base Color") at 0x00000252B8E6B408>
# <bpy_struct, NodeSocketFloatFactor("Subsurface") at 0x00000252B8E6B208>
# <bpy_struct, NodeSocketVector("Subsurface Radius") at 0x00000252B8E6B008>
# <bpy_struct, NodeSocketColor("Subsurface Color") at 0x00000252B8E6AE08>
# <bpy_struct, NodeSocketFloatFactor("Subsurface IOR") at 0x00000252B8E6AC08>
# <bpy_struct, NodeSocketFloatFactor("Subsurface Anisotropy") at 0x00000252B8E6AA08>
# <bpy_struct, NodeSocketFloatFactor("Metallic") at 0x00000252B8E6A808>
# <bpy_struct, NodeSocketFloatFactor("Specular") at 0x00000252B8E6A608>
# <bpy_struct, NodeSocketFloatFactor("Specular Tint") at 0x00000252B8E6A408>
# <bpy_struct, NodeSocketFloatFactor("Roughness") at 0x00000252B8E6A208>
# <bpy_struct, NodeSocketFloatFactor("Anisotropic") at 0x00000252B8E6A008>
# <bpy_struct, NodeSocketFloatFactor("Anisotropic Rotation") at 0x00000252B8E69E08>
# <bpy_struct, NodeSocketFloatFactor("Sheen") at 0x00000252B8E69C08>
# <bpy_struct, NodeSocketFloatFactor("Sheen Tint") at 0x00000252B8E69A08>
# <bpy_struct, NodeSocketFloatFactor("Clearcoat") at 0x00000252B8E69808>
# <bpy_struct, NodeSocketFloatFactor("Clearcoat Roughness") at 0x00000252B8E69608>
# <bpy_struct, NodeSocketFloat("IOR") at 0x00000252B8E69408>
# <bpy_struct, NodeSocketFloatFactor("Transmission") at 0x00000252B8E69208>
# <bpy_struct, NodeSocketFloatFactor("Transmission Roughness") at 0x00000252B8E69008>
# <bpy_struct, NodeSocketColor("Emission") at 0x00000252B8E68E08>
# <bpy_struct, NodeSocketFloat("Emission Strength") at 0x00000252B8E68C08>
# <bpy_struct, NodeSocketFloatFactor("Alpha") at 0x00000252B8E68A08>
# <bpy_struct, NodeSocketVector("Normal") at 0x00000252B8E68808>
# <bpy_struct, NodeSocketVector("Clearcoat Normal") at 0x00000252B8E68608>
# <bpy_struct, NodeSocketVector("Tangent") at 0x00000252B8E68408>
# <bpy_struct, NodeSocketFloat("Weight") at 0x00000252B8E53A08>

        # BAKING TIME!!!
        self.nodes_to_delete_during_cleanup = []
        for baking_pass in baking_passes:
            self.initialize_baker_texture(baking_pass)
            self.create_baking_image_texture_node(material_to_bake, baking_pass)

            # Normal will use the normal bake setting and the default connection, emission will use the default connection # TODO, handle this better
            if baking_pass not in ["Normal", "Emission"]:
                self.hook_up_node_for_bake(material_to_bake, baking_pass)

            # TODO finish implementing the texutre outputs and remove duplicate code
            output_file = bpy.path.abspath(self.settings.export_path)
            output_file += self.settings.texture_set_name

            # Perform the bake
            if baking_pass == "Normal":
                bpy.ops.object.bake(type = 'NORMAL', margin = 0, use_selected_to_active = False, use_clear = False)
                output_file += self.settings.suffix_normal + ".tif"
            elif baking_pass == "Base Color":
                bpy.ops.object.bake(type = 'EMIT', margin = 0, use_selected_to_active = False, use_clear = False)
                output_file += self.settings.suffix_basecolor + ".tga"
            else:
                bpy.ops.object.bake(type = 'EMIT', margin = 0, use_selected_to_active = False, use_clear = False)

            self.image_settings[baking_pass].apply_properties_to_object(context.scene.render.image_settings)
            self.baked_image_node.image.save_render(filepath = output_file)

            # Clean up
            for node in self.nodes_to_delete_during_cleanup:
                material_to_bake.node_tree.nodes.remove(node) # Remove the node
            self.nodes_to_delete_during_cleanup.clear()

            try:
                self.cached_material_output_links[material_to_bake].apply_link_to_node_tree(material_to_bake.node_tree) # Hook up the original node to the output
            except LinkFailedError as error:
                self.report({"WARNING"}, error.message)
                return

        # Set the render setting and cycles settings back to their original values
        render_settings_original.apply_properties_to_object(context.scene.render)
        cycles_settings_original.apply_properties_to_object(context.scene.cycles)
        context.scene.display_settings.display_device = display_device_original

        return {'FINISHED'}

    def cache_material_output_link(self, material):
        """Cache the original link to the output node so it can be recovered later"""
        # TODO make this support all outputs (Surface, Volume, Displacement), not just the Surface output
        # TODO make sure this handles with there is nothing hooked up to the output node

        node_output = material.node_tree.nodes["Material Output"] # Get the output node
        original_link = CachedNodeLink(node_output.inputs[0].links[0]) # Cache the details of the link to the output node
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

        if len(node_shader.inputs[baking_pass].links):
            input_node_name = node_shader.inputs[baking_pass].links[0].from_node.name
            input_socket_name = node_shader.inputs[baking_pass].links[0].from_socket.name
            node_input = material.node_tree.nodes[input_node_name]
            material.node_tree.links.new(node_emission.inputs[0], node_input.outputs[input_socket_name])
        else:
            input_type = node_emission.inputs[0].type
            if input_type == 'RGBA': # TODO figure out why this was causing problems
                # node_emission.inputs[0].default_value = node_shader.inputs[baking_pass].default_value
                return
            elif input_type == 'VALUE':
                node_value = material.node_tree.nodes.new('ShaderNodeValue')
                self.nodes_to_delete_during_cleanup.append(node_value)
                node_value.outputs[0].default_value = node_shader.inputs[baking_pass].default_value
                material.node_tree.links.new(node_emission.inputs[0], node_value.outputs[0])
            elif input_type == 'VECTOR':
                print("Please handle other types as well") # TODO
            else:
                print("Please handle other types as well") # TODO

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
                x = self.image_settings["Base Color"] = CachedProperties(cache_to_copy = common_settings)
                x.set_property("file_format", 'TARGA')
                x.set_property("color_depth", '8')
                x.set_property("linear_colorspace_settings.is_data", False)
                x.set_property("linear_colorspace_settings.name", 'sRGB')
            
            # Setup the appropriate output settings for roughness
            if self.settings.baking_pass_roughness:
                x = self.image_settings["Roughness"] = CachedProperties(cache_to_copy = common_settings)
                # TODO

            # Setup the appropriate output settings for metalness
            if self.settings.baking_pass_metalness:
                x = self.image_settings["Metallic"] = CachedProperties(cache_to_copy = common_settings)
                # TODO

            # Setup the appropriate output settings for normal
            if self.settings.baking_pass_normal:
                x = self.image_settings["Normal"] = CachedProperties(cache_to_copy = common_settings)
                x.set_property("file_format", 'TIFF')
                x.set_property("color_depth", '16')
                x.set_property("linear_colorspace_settings.is_data", True)
                x.set_property("linear_colorspace_settings.name", 'Raw')
        
            # Setup the appropriate output settings for emission
            if self.settings.baking_pass_emission:
                x = self.image_settings["Emission"] = CachedProperties(cache_to_copy = common_settings)
                # TODO
    
    def initialize_baker_texture(self, suffix):
        # TODO handle this better
        if suffix == "Base Color":
            suffix = self.settings.suffix_basecolor
        if suffix == "Roughness":
            suffix = self.settings.suffix_roughness
        if suffix == "Metallic":
            suffix = self.settings.suffix_metalness
        if suffix == "Normal":
            suffix = self.settings.suffix_normal
        if suffix == "Emission":
            suffix = self.settings.suffix_emission

        new_texture = "_".join([self.settings.texture_set_name, suffix])

        # Remove the texture if it already exists so that it can be reinitialized with the correct resolution and settings
        image = bpy.data.images.get(new_texture, None)
        if image: bpy.data.images.remove(image, do_unlink = True)

        # Create the new texture
        bpy.data.images.new(name = new_texture, width = self.settings.texture_size, height = self.settings.texture_size, float_buffer = True) #TODO float_buffer not needed for RGB

        # Save the new texture in a variable where we can reference it later
        self.settings.baker_texture = bpy.data.images.get(new_texture, None)

    def create_baking_image_texture_node(self, material, baking_pass):
        
        # TODO make this correct for each pass.
        if baking_pass == "Base Color":
            color_space = "sRGB"
        else:
            color_space = "Non-Color"

        self.baked_image_node = material.node_tree.nodes.new('ShaderNodeTexImage')
        self.nodes_to_delete_during_cleanup.append(self.baked_image_node)
        self.baked_image_node.location = [0, 0]
        self.baked_image_node.label = 'BakerTexture'
        self.baked_image_node.name = 'BakerTexture'
        self.baked_image_node.image = self.settings.baker_texture
        self.baked_image_node.image.colorspace_settings.name = color_space
        self.baked_image_node.select = True # Make the node the active selection so that it will receive the bake.
        material.node_tree.nodes.active = self.baked_image_node # Make the new node the active node so that it will receive the bake.

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