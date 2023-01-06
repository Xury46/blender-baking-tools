bl_info = {
    "name" : "caching_utilities",
    "author" : "Xury Greer",
    "version" : (0, 1),
    "blender" : (3, 4, 1),
    "location" : "",
    "warning" : "",
    "wiki_url" : "",
    "category" : "Development",
}

import bpy
import functools

#{ CACHED_RNA_REGION
class CachedProperties():
    """Blender's built in types (bpy.types) are handled through the "bl_rna" data access system and can't be instantiated manually like regular objects.
    This system has positives in the Blender API, but it prevents us from easily caching data from these objects using a copy constructor.
    This is particularly preventative for working with RenderSettings and BakeSettings where the data access won't even allow us to make temporary copies of these objects since they belong to the Scene data-block and only one instance of each is allowed to exist in the scene.
    This helper class will allow us to cache all of the settings for Blender's built-in bpy_struct types into a dictionary to work around this limitation.

    Read more about Blender's DNA/RNA structure:
    https://docs.blender.org/api/current/bpy.data.html
    https://wiki.blender.org/wiki/Source/Architecture/RNA
    https://www.blendernation.com/2008/12/01/blender-dna-rna-and-backward-compatibility/
    https://docs.blender.org/api/current/bpy.types.RenderSettings.html
    """
    UNASSIGNED_VALUE = "UNASSIGNED_VALUE" # Use this as a flag instead of "None" in case a property makes use of NoneType, empty strings, or other falsy values

    def __init__(self, object_to_cache = None, cache_to_copy = None, dont_assign_values = False):
        """This will act like a pseudo copy constructor for the bpy_struct object that is passed in. A deep copy of all property values will be cached into a dictionary.

        In order to recursively cache PointerProperties of a bpy_struct, we have to read values from an instance.
        Passing in an object type instead of an instance will not work because its PointerProperties will be blank, so we can't get the properties that belong to that subobject.
        If we copy values from an instance, this is not an issue, since the PointerProperties will be set to point at their appropriate subobjects.

        We might only want to keep a list of the properties WITHOUT their values.
        If dont_assign_values is true, all of the values in the "properties" dictionary will be set to UNASSIGNED_VALUE.
        The dictionary's keys will be retained, so we'll still have all of the property names that belong to the cached object.

        Example:
        "bpy.types.RenderSettings" has a PointerProperty called "bake" which is supposed to point at a "bpy.types.BakeSettings" object, but there's no way to know this before the RenderSettings object has been initialized
        The instance "bpy.context.scene.render" has been initialized so its "bake" PointerProperty points to an initialized "BakeSettings" object, and we are able to read its property values."""

        # Determine if we are copying properties from an initialized bpy_struct, or by copying properties from an existing CachedProperties object
        if object_to_cache and cache_to_copy:
            raise TypeError("Too many arguments: Either object_to_cache OR cache_to_copy (not both) must be passed in to initialize this object.")

        # Initialize with a bpy_struct object
        if object_to_cache:
            self.top_level_object = object_to_cache

            # Determine the type of the object that this object will cache properties for
            self.object_type = type(object_to_cache) # Get the type of the object_to_cache
            # Check if the provided object_to_cache is a bpy_struct
            if not issubclass(self.object_type, bpy.types.bpy_struct):
                raise TypeError("The provided object {o} is a {t} not a bpy_struct, its properties can't be cached in this object.".format(o = object_to_cache, t = self.object_type))

            # Make a dictionary of the top-level properties for the object that this object will cache
            self.properties = self.build_properties_dictionary(object_to_cache)

            self.still_has_subproperties = True # TODO make this based on number of PointerProperties which won't always be greater than 0 on the first iteration
            while self.still_has_subproperties:
                self.get_subproperties()

        # Initialize with an existing CachedProperties object
        elif cache_to_copy:
            self.top_level_object = cache_to_copy.top_level_object
            self.object_type =      cache_to_copy.object_type

            properties_deep_copy = {}
            for key, value in cache_to_copy.properties.items():
                properties_deep_copy[key] = value
            self.properties = properties_deep_copy

            self.still_has_subproperties = False

        else:
            raise TypeError("Not enough arguments: Either object_to_cache OR cache_to_copy must be passed in to initialize this object.")

        if dont_assign_values:
            self.unassign_values_in_properties_dictionary()

    def unassign_values_in_properties_dictionary(self):
        """Set all of the values in the properties dictionary to UNASSIGNED_VALUE"""

        for key in self.properties.copy(): # Make a temporary copy so we aren't editing the values of the dictionary while iterating through it
            self.properties[key] = self.UNASSIGNED_VALUE # Set each of the values to the UNASSIGNED_VALUE

    def get_subproperties(self):
    # Get the properties from the pointer properties...
        pointer_property_paths = [] # Keep a list of properties that are of type bpy.types.PointerProperty
        subproperties = {}
        unset_pointer_property_paths = [] # Some pointer properties such as "bake.cage_object", "image_settings.view_settings.curve_mapping", and "bake.image_settings.view_settings.curve_mapping" may not be set, the value for these properties should be set to None
        for property_path, property_value in self.properties.items():
            if issubclass(type(property_value), bpy.types.bpy_struct):
                try:
                    # TODO Find a way to check if the PointerProperty points at a fixed_type or if it is unset and points at NoneType before trying to build the properties dictionary
                    # .fixed_type points at the actual object instead of the PonterProperty itself
                    props = self.build_properties_dictionary(property_value.fixed_type, breadcrumbs= property_path)
                    pointer_property_paths.append(property_path)
                    subproperties.update(props) # Append this props dictionary to the subproperties dictionary
                except AttributeError as e:
                    # if the pointer property points to a UI element that hasn't been set by the user then it will return NoneType, which will be caught by this exception
                    # print(repr(e))
                    unset_pointer_property_paths.append(property_path)

        for unset_pointer_property_path in unset_pointer_property_paths:
            self.properties[unset_pointer_property_path] = None

        if len(pointer_property_paths):
            # Now that we've gotten the subproperties of the pointer properties, remove the pointer property keys from the dictionary
            for pointer_property_path in pointer_property_paths:
                del self.properties[pointer_property_path]

            # Append the new subproperties to the self.properties dictionary
            self.properties.update(subproperties)
        else:
            self.still_has_subproperties = False

    def build_properties_dictionary(self, object_to_copy_from, breadcrumbs = None):
        """This will return a list of properties for the given bpy_struct object
            Some of the properties we want are stored inside of readonly subobjects
            Example: the bpy_struct bpy.types.RenderSettings has a property "bake" which is itself a readonly bpy_struct of type bpy.types.BakeSettings
            If we want to cache the values for each of these bake settings as well, we will need go through the bpy_struct properties recursively #TODO fix this definition to be more accurate to the implementation
        """

        # The bpy.types.Property.__subclasses__() list has two types that are problematic and throw false positives when checking property types of a class.
        complex_property_types = [bpy.types.PointerProperty, bpy.types.CollectionProperty]
        basic_property_types = [] # Auto populate this list, in Blender 3.4.1 this list comprises class references for the following bpy.types:
                                  # EnumProperty, PointerProperty, FloatProperty, IntProperty, BoolProperty, StringProperty, CollectionProperty
        # Make a list of potential property types, excluding the complex types that can trigger false positives
        for subclass in bpy.types.Property.__subclasses__():
            if subclass not in complex_property_types: # Exclude the complex types from the list of basic types
                basic_property_types.append(subclass)
        # TODO do this ^ once for the CachedProperties class since this doesn't change.

        new_properties = {}
        for property in object_to_copy_from.bl_rna.properties: # Get the list of properties from this bpy_struct
            if property.identifier == 'rna_type': # exclude the "rna_type" property
                continue

            property_type = type(property)

            if property_type in basic_property_types: # Check if the property is a basic type
                if breadcrumbs:
                    property_with_breadcrumbs = ".".join([str(breadcrumbs), property.identifier]) # Create the full path to the property by adding its breadcrumbs. Example: "render.bake" + "."  + "margin"
                    property_value = functools.reduce(getattr, property_with_breadcrumbs.split("."), self.top_level_object) # Follow the breadcrumbs until we arrive at the bottom-most property so we can get its value

                    new_properties[property_with_breadcrumbs] = property_value # Add the property value to the dictionary with its full breadcrumb path and identifier as the key
                    continue
                else:
                    new_properties[property.identifier] = getattr(self.top_level_object, property.identifier) # Add the property value to the dictionary with its identifier as the key

            elif property_type == bpy.types.CollectionProperty:
                # TODO do collection property things here... https://docs.blender.org/api/current/bpy.types.bpy_prop_collection.html
                # for i in property.items():
                #     print(i)
                # properties_from_struct.append(property.identifier)
                continue

            # If this is a pointer property, it points to a different bpy_struct object.
            # For now, well store a reference to this object as a value in the dictionary with its full breadcrumb path as the key
            # We will come back later to get the values of each of its properties 
            elif property_type == bpy.types.PointerProperty:
                if breadcrumbs:
                    property_with_breadcrumbs = ".".join([str(breadcrumbs), property.identifier])
                    new_properties[property_with_breadcrumbs] = property
                else:
                    new_properties[property.identifier] = property

        return new_properties

    def set_property(self, property, value):
        """Set a property value"""
        if property not in self.properties.keys():
            raise KeyError("{s} was initialized to store {i} data, which has no \"{p}\" property".format(s = self, i = self.object_type, p = property))

        # Update the value in the dictionary
        self.properties[property] = value

    def set_properties(self, **kwargs):
        """Set an arbitrary amount of property values, these will override values set in the pseudo 'copy constructor'"""
        for key, value in kwargs.items():
            self.set_property(key, value)

    def get_valid_enum_options(self, object, property):
        # Blender's EnumProperties are dynamic, in several cases they are initialized with ['NONE'], then Blender handles adding enum_items later.
        # Problem: Querying property.enum_items in Python does not return the current list of enum_items, it only returns the items that were available at initialization which is often: ['NONE']
        # However, an error will be thrown when trying to set the EnumProperty with an incorrect value, the error will contain a current list of enum_items
        # HACK: Intentionally try to set the property with an incorrect value, then get the list of valid options from the error message.
        try:
            setattr(object, property.identifier, "INTENTIONALLY_INCORRECT_VALUE")
        except TypeError as e:
            # This error will return a message:                                               "bpy_struct: item.attr = val: enum "INTENTIONALLY_INCORRECT_VALUE" not found in ('Example 1', 'Example 2')"
            items = str(e).rsplit('(') # Remove the first part of the error message:          "bpy_struct: item.attr = val: enum "INTENTIONALLY_INCORRECT_VALUE" not found in ("
            items = items[1].rsplit(')')[0] # Remove the closing parenthesis:                 ")"
            items = items.replace("'", "") # Remove the quotation marks that wrap each entry: 'Example 1', 'Example 2' -> Example 1, Example 2
            enum_items = items.split(", ") # Separate the items to make the final list:       ['Example 1', 'Example 2']

        return enum_items

    def apply_properties_to_object(self, top_level_object):
        """Apply the properties to the given object"""
        if not isinstance(top_level_object, self.object_type):
            raise TypeError("{s} was initialized to store {i} data. It can't apply its properties to {o} which is a {t} type".format(s = self, i = self.object_type, o = top_level_object, t = type(top_level_object)))

        properties_that_failed_to_apply = {}

        # Check each of the assigned settings, if they have values in the dictionary, assign them
        for property, value in self.properties.items():
            # If the value was never assigned, skip this property
            if value == self.UNASSIGNED_VALUE:
                continue

            object_to_update = top_level_object
            property_to_update = property

            # If the property_to_update doesn't directly belong to the top_level_object, we need to drill down to get a reference to the object_to_update that the property does belong to
            if "." in property:
                # Set the property on a nested object
                path, property_to_update = property.rsplit(".", 1) # Split the bread crumb path, store the first element on the right and the name of the property_to_update
                path = path.split(".") # Split the remainder of the path
                object_to_update = top_level_object # Start at the top_level_object before we drill down through its nested subobjects
                # Drill down through the list of objects until we have a reference to the object that the property_to_update belongs to
                while path:
                    subobject, path = path[0], path[1:]
                    object_to_update = getattr(object_to_update, subobject)

            property_to_check = object_to_update.bl_rna.properties[property_to_update] # Get the property by name from the class

            # If the property is read-only skip it
            if property_to_check.is_readonly:
                continue

            # Check if the value we're trying to apply is valid for the property
            property_type = type(property_to_check)
            object_type = type(object_to_update)

            # Check valid options in enums
            if property_type == bpy.types.EnumProperty:
                valid_options = self.get_valid_enum_options(object_to_update, property_to_check)

                if value not in valid_options:
                    properties_that_failed_to_apply[property] = (value, valid_options) # Keep track of the property that couldn't be applied
                    continue
                    # raise TypeError("The \"{p}\" property can only take values from the following enum_items: {e}. \"{v}\" is not a valid option".format(p = property, e = valid_options, v = value))

            # TODO validate other types not just Enums
                # raise TypeError("The \"{p}\" property can only take values of type {t}. {v} can't be assigned to it".format(p = key, t = property_type, v = value))

            # Apply the cached value to the object's property
            setattr(object_to_update, property_to_update, value)
        
        if len(properties_that_failed_to_apply):
            print("Failed to assign the following properties:")
            longest_key = max(properties_that_failed_to_apply.keys(), key=len)
            for key, value in properties_that_failed_to_apply.items():
                print("{p: <{l}} | The provided value \"{v}\" was not in {i}".format(l=len(longest_key), p= key, v= value[0], i= value[1]))

    def print_cached_properties(self):
        longest_key = max(self.properties.keys(), key=len)
        for key, value in self.properties.items():
            print("{p: <{l}} | {v}".format(l=len(longest_key), p=key, v=value))

#} END CACHED_RNA_REGION

#{ NODE_LINKS_REGION
class LinkFailedError(Exception):
    def __init__(self, message):
        self.message = message

class CachedNodeLink():
    """Caches a link between node sockets so it can be restored after edits have been made to the node tree
        Raises LinkFailedError if nodes or sockets are missing while trying to apply the link
    """
    def __init__(self, link):
        # Store the names of each component of the link instead of the link itself.
        # This gives a deep copy that won't get messed up when edits are made to the node tree
        self.from_node_name = link.from_node.name      # Name of the node on the left side that is outputing the link
        self.from_socket_name = link.from_socket.name  # Name of the socket that is outputting the link
        self.to_node_name = link.to_node.name          # Name of the node on the right side that is receiving the input link
        self.to_socket_name = link.to_socket.name      # Name of the socket that is receiving the input link

    def apply_link_to_node_tree(self, node_tree):
        # Check for errors in the "from" node
        if self.from_node_name not in node_tree.nodes.keys():
            raise LinkFailedError(message = "Node link could not be made in {tree} because {node} was not found in the node tree.".format(tree = node_tree, node = self.from_node_name))
        from_node = node_tree.nodes[self.from_node_name] # Find the node in the given node tree.
        if self.from_socket_name not in from_node.outputs:
            raise LinkFailedError(message = "Node link could not be made in {tree} because {node} does not have the required {socket} output socket.".format(tree = node_tree, node = self.from_node_name, socket = self.from_socket_name))
        from_socket = from_node.outputs[self.from_socket_name] # Find the socket in the given node.

        # Check for errors in the "to" node
        if self.to_node_name not in node_tree.nodes.keys():
            raise LinkFailedError(message = "Node link could not be made in {tree} because {node} was not found in the node tree.".format(tree = node_tree, node = self.to_node_name))
        to_node = node_tree.nodes[self.to_node_name] # Find the node in the given node tree.
        if self.to_socket_name not in to_node.inputs:
            raise LinkFailedError(message = "Node link could not be made in {tree} because {node} does not have the required {socket} input socket.".format(tree = node_tree, node = self.to_node_name, socket = self.to_socket_name))
        to_socket = to_node.inputs[self.to_socket_name] # Find the socket in the given node.

        node_tree.links.new(to_socket, from_socket) # Make the link
#} END NODE_LINKS_REGION