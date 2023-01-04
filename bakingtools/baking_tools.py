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

class OBJECT_OT_BatchBake(bpy.types.Operator):
    """Batch bake textures"""
    bl_label = "BatchBake"
    bl_idname = "object.batch_baker"
    bl_description = "Batch bakes textures"

    bakeable_types = ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME')

    def execute(self, context):
        self.settings = context.scene.baking_tools_settings

        # Cache the original render settings and cycles settings so they can be restored later
        render_settings_original = cache.CachedProperties(object_to_cache = context.scene.render)
        cycles_settings_original = cache.CachedProperties(object_to_cache = context.scene.cycles)
        display_device_original = context.scene.display_settings.display_device

        # Set up the image settings that will be used for each baking pass
        try:
            self.image_settings = {} # Keep a dictionary of the image settings for each baking pass since the Baking_Pass class can't retain values for properties that don't inherit from Blender's Property class
            self.setup_image_settings()
        except KeyError as e:
            print(repr(e))
            return {'CANCELLED'}

        # Cache the original selection and original active object
        self.original_selection = context.selected_objects 
        self.original_active = context.active_object

        # Deselect everything
        for object in bpy.data.objects:
            object.select_set(False)
        context.view_layer.objects.active = None

        object_to_bake = None # TODO make this work for each object that's selected, not just the final object
        if self.settings.bake_source == "SELF":
            for object in self.original_selection:
                if object.type not in self.bakeable_types:
                    continue
                # Select the object and make it active
                object_to_bake = object
                object_to_bake.select_set(True)
                context.view_layer.objects.active = object_to_bake
        if not object_to_bake:
            return {'CANCELLED'}

        self.cached_material_output_links = {} # Keep track of all of the original node connections in a dictionary

        material_to_bake = object_to_bake.data.materials[0] # TODO make this work for multi-material setups
        self.cache_material_output_link(material_to_bake)

        # Set up the render settings and cycles settings for baking
        render_settings_bake = cache.CachedProperties(cache_to_copy = render_settings_original, dont_assign_values=True)
        render_settings_bake.set_property("engine", 'CYCLES')
        render_settings_bake.set_property("use_file_extension", True)
        render_settings_bake.set_property("bake.target", 'IMAGE_TEXTURES')

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
        baking_passes = bpy.context.scene.baking_passes
        for baking_pass in baking_passes:
            if not baking_pass.enabled:
                continue

            self.initialize_baker_texture(baking_pass)
            self.create_baking_image_texture_node(material_to_bake, baking_pass)

            # Normal will use the normal bake setting and the default connection, emission will use the default connection # TODO, handle this better
            if baking_pass.name not in ["Normal", "Emission"]:
                self.hook_up_node_for_bake(material_to_bake, baking_pass)

            self.image_settings[baking_pass].apply_properties_to_object(context.scene.render.bake.image_settings) # Apply the settings so that the bake happens with the correct settings
            self.image_settings[baking_pass].apply_properties_to_object(context.scene.render.image_settings) # Apply the settings so that the texture output happens with the correct settings

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

            extension = None
            # Get the file extension
            for format in File_Format_Info.get_file_formats():
                if texture_format == format[0]:
                    extension = format[1] # Example: Look up "PNG", return ".png"
                    break

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

        # Deselect everything
        for object in bpy.data.objects:
            object.select_set(False)

        # Reselect everything from the original selection and set the active object back to the original active object
        for object in self.original_selection:
            object.select_set(True)
        context.view_layer.objects.active = self.original_active

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

        # If there are links to the socket, hook them up to the emission node
        socket = node_shader.inputs[baking_pass.name]
        if len(socket.links):
            input_node_name = socket.links[0].from_node.name
            input_socket_name = socket.links[0].from_socket.name
            node_input = material.node_tree.nodes[input_node_name]
            material.node_tree.links.new(node_emission.inputs[0], node_input.outputs[input_socket_name])
        # If there are no links to the socket, assign the socket's default_value to the emission node
        else:
            if socket.type == 'RGBA':
                node_emission.inputs[0].default_value = socket.default_value
                return
            elif socket.type == 'VALUE':
                node_value = material.node_tree.nodes.new('ShaderNodeValue')
                self.nodes_to_delete_during_cleanup.append(node_value)
                node_value.outputs[0].default_value = node_shader.inputs[baking_pass.name].default_value
                material.node_tree.links.new(node_emission.inputs[0], node_value.outputs[0])
            elif socket.type == 'VECTOR':
                print("Please handle other types as well") # TODO
            else:
                print("Please handle other types as well") # TODO

    def setup_image_settings(self):
        # Create the core image settings that are common for all types of baking
        common_image_settings = cache.CachedProperties(object_to_cache = bpy.context.scene.render.bake.image_settings, dont_assign_values=True)
        common_image_settings.set_property("color_management", 'OVERRIDE')
        common_image_settings.set_property("color_mode", 'RGB')
        common_image_settings.set_property("tiff_codec", 'DEFLATE')
        common_image_settings.set_property("view_settings.look", 'None')
        common_image_settings.set_property("view_settings.use_curve_mapping", False)
        common_image_settings.set_property("view_settings.view_transform", 'Raw')

        # Get the collection property of baking passes
        baking_passes = bpy.context.scene.baking_passes
        for baking_pass in baking_passes:
            image_settings = cache.CachedProperties(cache_to_copy = common_image_settings)
            image_settings.set_property("file_format", baking_pass.file_format)
            image_settings.set_property("color_depth", baking_pass.color_depth)

            if baking_pass.name == "Base Color":
                image_settings.set_property("linear_colorspace_settings.is_data", False)
                image_settings.set_property("linear_colorspace_settings.name", 'sRGB')
                baking_pass.texture_node_color_space = 'sRGB'

            elif baking_pass.name in ["Roughness", "Metallic", "Normal"]:
                image_settings.set_property("linear_colorspace_settings.is_data", True)
                image_settings.set_property("linear_colorspace_settings.name", 'Raw')
                baking_pass.texture_node_color_space = 'Non-Color'

            elif baking_pass.name == "Emission":
                image_settings.set_property("linear_colorspace_settings.is_data", False)
                image_settings.set_property("linear_colorspace_settings.name", 'sRGB')
                baking_pass.texture_node_color_space = 'Non-Color'

            self.image_settings[baking_pass] = image_settings

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

class File_Format_Info():
    # https://docs.blender.org/manual/en/2.79/data_system/files/media/image_formats.html

    @staticmethod
    def get_file_formats():
        file_formats = [# ("BMP",                 ".bmp", ""),
                        ("PNG",                 ".png", ""),
                        # ("JPEG",                ".jpg", ""),
                        ("TARGA",               ".tga", ""),
                        # ("TARGA_RAW",           ".tga", ""),
                        # ("OPEN_EXR_MULTILAYER", ".exr", ""),
                        ("OPEN_EXR",            ".exr", ""),
                        ("HDR",                 ".hdr", ""),
                        ("TIFF",                ".tif", "")]

        return file_formats

    @staticmethod
    def get_color_depths(file_format):
        if file_format in ('BMP', 'JPEG', 'TARGA', 'TARGA_RAW'):
            return [('8',   '8', "")]
        if file_format in ('IRIS', 'PNG', 'TIFF'):
            return [('8',   '8', ""),
                    ('16', '16', "")]
        if file_format in ('JPEG2000'):
            return [('8',   '8', ""),
                    ('12', '12', ""),
                    ('16', '16', "")]
        if file_format in ('CINEON', 'DPX'):
            return [('8',   '8', ""),
                    ('10', '10', ""),
                    ('12', '12', ""),
                    ('16', '16', "")]
        if file_format in ('OPEN_EXR_MULTILAYER', 'OPEN_EXR'): # TODO make sure file output respects the Full-Float vs Half-Float for this file type
            return [('16', '16', ""),
                    ('32', '32', "")]
        if file_format in ('HDR'):
            return [('32', '32', "")]
        raise KeyError

# This callback gets called automatically to update the item list
def update_color_depths(self, context):
    return File_Format_Info.get_color_depths(self.file_format)

class Baking_Pass(bpy.types.PropertyGroup):
    name        : bpy.props.StringProperty(name= "Name",        default= "")
    enabled     : bpy.props.BoolProperty(  name= "Enabled",     default= True)
    suffix      : bpy.props.StringProperty(name= "Suffix",      default= "")
    file_format : bpy.props.EnumProperty(  name= "File format", items= File_Format_Info.get_file_formats(), default= 'PNG', update= update_color_depths)
    color_depth : bpy.props.EnumProperty(  name= "Color depth", items= update_color_depths)

    # Not used in UI, but must be bound to a Property so its values are retained
    texture_node_color_space : bpy.props.StringProperty() # 'Filmic Log', 'Filmic sRGB', 'Linear', 'Linear ACES', 'Linear ACEScg', 'Non-Color', 'Raw', 'sRGB', 'XYZ'
    # invert_roughness : bpy.props.BoolProperty(name = "Invert Roughness", default = False) # TODO add this as an extension for roughness and normal...

class BakingTools_Props(bpy.types.PropertyGroup):
    """Properties to for baking"""
    texture_set_name : bpy.props.StringProperty(name = "Texture Set name", default = "BakedTexture", subtype='FILE_NAME')
    texture_size : bpy.props.IntProperty(name = "Resolution", default = 1024)
    baker_texture : bpy.props.PointerProperty(name = "Texture Image", type = bpy.types.Image)

    export_path : bpy.props.StringProperty(name = "Output Path", subtype='DIR_PATH')

    bake_source : bpy.props.EnumProperty(name = "Bake from:",
                                    items=[
                                        ("SELF", "Self", "Material sockets will be baked to textures."),
                                        ("SELECTED_TO_ACTIVE", "Selected To Active", "High-res objects will be baked to low-res object based on selection."),
                                        ("UI_LIST", "UI List", "High-res objects will be baked to low-res object based on UI list.")
                                    ],
                                    default="SELF")

class VIEW_3D_PT_BakingTools(bpy.types.Panel):
    """Create a panel UI in Blender's 3D Viewport Sidebar"""
    bl_label = "Baking Tools"
    bl_idname = "VIEW_3D_PT_BAKINGTOOLS"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Baking Tools'

    def draw(self, context):
        settings = context.scene.baking_tools_settings
        baking_passes = context.scene.baking_passes

        layout = self.layout
        row = layout.row()
        split = row.split(factor= 0.3)

        # Checkboxes for baking passes
        column = split.column()
        column.label(text = "Baking Passes:")
        for baking_pass in baking_passes:
            column.prop(baking_pass, 'enabled', text = baking_pass.name)

        # Textboxes for baking pass suffixes
        column = split.column()
        column.label(text = "Suffix:")
        for baking_pass in baking_passes:
            column.prop(baking_pass, 'suffix', text = "")

        split = split.split() # Make a second split

        # Dropdown lists for baking pass file formats
        column = split.column()
        column.label(text = "Format:")
        for baking_pass in baking_passes:
            column.prop(baking_pass, 'file_format', text = "")

        split = split.split() # Make a third split

        # Dropdown lists for baking pass color depth
        column = split.column()
        column.label(text = "Depth:")
        for baking_pass in baking_passes:
            available_depths = File_Format_Info.get_color_depths(baking_pass.file_format)
            if len(available_depths) == 1:
                # If there is only one option, display it as a label in the UI
                column.label(text = available_depths[0][0]) # Get the first and only option, and get the first entry from the corresponding tuple
            else:
                # Display the list of relevant color depth options for this file format
                column.prop(baking_pass, 'color_depth', text = "")

        row = layout.row()
        row.prop(settings, 'texture_size')

        row = layout.row()
        row.prop(settings, 'export_path')

        row = layout.row()
        row.prop(settings, 'texture_set_name')

        row = layout.row()
        row.label(text = "Bake from:")
        row.prop(settings, 'bake_source', expand=True)

        row = layout.row()
        row.operator('object.batch_baker', icon = 'RENDER_STILL')

def new_baking_pass(name, enabled, suffix, file_format, color_depth):
    baking_passes = bpy.context.scene.baking_passes
    new_baking_pass = baking_passes.add()

    new_baking_pass.name        = name
    new_baking_pass.enabled     = enabled
    new_baking_pass.suffix      = suffix
    new_baking_pass.file_format = file_format
    new_baking_pass.color_depth = color_depth

def setup_baking_passes():
    # Get the collection property of baking passes
    baking_passes = bpy.context.scene.baking_passes
    baking_passes.clear() # Clear the list so that no previous entries are retained

    # Add the baking passes:
    new_baking_pass(name = "Base Color", enabled = True, suffix = "BaseColor", file_format = 'PNG',  color_depth = '8' )
    new_baking_pass(name = "Roughness",  enabled = True, suffix = "Roughness", file_format = 'PNG',  color_depth = '8' )
    new_baking_pass(name = "Metallic",   enabled = True, suffix = "Metal",     file_format = 'PNG',  color_depth = '8' )
    new_baking_pass(name = "Normal",     enabled = True, suffix = "Normal",    file_format = 'TIFF', color_depth = '16')
    new_baking_pass(name = "Emission",   enabled = True, suffix = "Emit",      file_format = 'PNG',  color_depth = '8' )

# Register the add-on in Blender
classes = [Baking_Pass, BakingTools_Props, OBJECT_OT_BatchBake, VIEW_3D_PT_BakingTools]

def register():
    bpy.utils.register_class(Baking_Pass) # Register the Baking_Pass class
    bpy.types.Scene.baking_passes = bpy.props.CollectionProperty(type = Baking_Pass) # Create a collection of baking passes for the scene 
    setup_baking_passes() # Set up all of the settings for each of the baking passes

    bpy.utils.register_class(BakingTools_Props) # Register the Baking_Pass class
    bpy.types.Scene.baking_tools_settings = bpy.props.PointerProperty(type = BakingTools_Props)

    # Register the classes
    for cls in [OBJECT_OT_BatchBake, VIEW_3D_PT_BakingTools]:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    # Delete the settings and baking passes
    baking_passes = bpy.context.scene.baking_passes
    baking_passes.clear()

    del bpy.context.scene.baking_tools_settings
    del baking_passes

if __name__ == "__main__":
    register()