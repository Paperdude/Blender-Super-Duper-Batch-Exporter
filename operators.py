
import bpy
import bpy.props as properties
import os
from pathlib import Path
import shutil

from bpy.types import Operator
from . import utils


# Operator called when pressing the batch export button.
class EXPORT_MESH_OT_batch(Operator):
    """Export many objects to seperate files all at once"""
    bl_idname = "export_mesh.batch"
    bl_label = "Batch Export"
    file_count = 0
    copy_count = 0

    def execute(self, context):
        settings = context.scene.batch_export

# 1. Get Project Directory from Preferences
        name = __package__
        pref_project_dir = ""
        if name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            if prefs and hasattr(prefs, 'project_dir'):
                pref_project_dir = prefs.project_dir

        # 2. Calculate Base Directory
        if pref_project_dir:
            # If Project Dir is set, it overrides the .blend file as the relative root
            raw_dir = settings.directory
            # Strip Blender's relative prefix '//' if present so it doesn't conflict
            if raw_dir.startswith('//'):
                 raw_dir = raw_dir[2:]
            
            # Combine Project Dir with Output Dir. 
            # If Output Dir is absolute (e.g. "C:\"), it will correctly override the join.
            base_dir = os.path.join(bpy.path.abspath(pref_project_dir), raw_dir)
            base_dir = os.path.normpath(base_dir)
            
        else:
            # Standard Blender behavior (relative to .blend file)
            base_dir = settings.directory
            if not bpy.data.is_saved:
                # If unsaved, we cannot use relative paths starting with //
                if base_dir.startswith("//"):
                    self.report(
                        {'ERROR'}, "Save .blend file before exporting to relative directory\n(or set a Project Directory in Preferences)")
                    return {'FINISHED'}
            base_dir = bpy.path.abspath(base_dir)

        # 3. Validate existence
        if not os.path.isdir(base_dir):
            msg = f"Export directory doesn't exist:\n{base_dir}"
            self.report({'ERROR'}, msg)
            print(msg) # Print to console for easier debugging of paths
            return {'FINISHED'}

        self.file_count = 0

        # Save current state of viewlayer, selection and active object to restore after export
        view_layer = context.view_layer
        selection = context.selected_objects
        obj_active = view_layer.objects.active   

        # Check if we're not in Object mode and set if needed
        obj_active = view_layer.objects.active        
        mode = ''
        if obj_active:
            mode = obj_active.mode
            bpy.ops.object.mode_set(mode='OBJECT')  # Only works in Object mode
        

        ##### EXPORT OBJECTS BASED ON MODES #####
        if settings.mode == 'OBJECTS':
            for obj in self.get_filtered_objects(context, settings):

                # Export Selection
                obj.select_set(True)
                self.export_selection(obj.name, context, base_dir)

                # Deselect Obj
                obj.select_set(False)

        elif settings.mode == 'PARENT_OBJECTS':
            exportObjects = self.get_filtered_objects(context, settings)

            for obj in exportObjects:
                if obj.parent in exportObjects:
                    continue  # if it has a parent, skip it for now, it'll be exported when we get to its parent

                # Export Selection
                obj.select_set(True)
                self.select_children_recursive(obj, context,)

                if context.selected_objects:
                    self.export_selection(obj.name, context, base_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        elif settings.mode == 'COLLECTIONS':
            exportobjects = self.get_filtered_objects(context, settings)

            for col in bpy.data.collections.values():
                # Check if collection objects are in filtered objects
                for obj in col.objects:
                    if not obj in exportobjects:
                        continue
                    obj.select_set(True)
                if context.selected_objects:
                    self.export_selection(col.name, context, base_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        # Functionality for both COLLECTION_SUBDIRECTORIES and COLLECTION_SUBDIR_PARENTS
        elif 'COLLECTION_SUBDIR' in settings.mode:
            exportobjects = self.get_filtered_objects(context, settings)

            for obj in exportobjects:
                if 'PARENT' in settings.mode and obj.parent in exportobjects:
                    continue  # if it has a parent, skip it for now, it'll be exported when we get to its parent

                # Modify base_dir to add collection, creating directory if necessary
                sCollection = obj.users_collection[0].name
                if sCollection != "Scene Collection":
                    if settings.full_hierarchy:
                        hierarchy = utils.get_collection_hierarchy(sCollection)
                        collection_dir = os.path.join(base_dir, hierarchy)
                    else:
                        collection_dir = os.path.join(base_dir, sCollection)

                    # create sub-directory if it doesn't exist
                    if not os.path.exists(collection_dir):
                        try:
                            os.makedirs(collection_dir)
                            print(f"Directory created: {collection_dir}")
                        except OSError as e:
                            self.report({'ERROR'}, f"Error creating directory {collection_dir}: {e}")
                else: # If object is just in Scene Collection it get's exported to base_dir
                    collection_dir = base_dir

                # Select
                obj.select_set(True)
                if 'PARENT' in settings.mode:
                    self.select_children_recursive(obj, context)

                # Export
                self.export_selection(obj.name, context, collection_dir)

                # Deselect
                for obj in context.selected_objects:
                    obj.select_set(False)

        elif settings.mode == 'SCENE':
            prefix = settings.prefix
            suffix = settings.suffix
            
            filename = ''
            if not prefix and not suffix:
                filename = bpy.path.basename(bpy.context.blend_data.filepath).split('.')[0]
            
            for obj in self.get_filtered_objects(context, settings):
                obj.select_set(True)
            self.export_selection(filename, context, base_dir)

        # Return selection to how it was
        bpy.ops.object.select_all(action='DESELECT')
        for obj in selection:
            obj.select_set(True)
        view_layer.objects.active = obj_active

        # Return to whatever mode the user was in
        if obj_active:
            bpy.ops.object.mode_set(mode=mode)

        # Report results
        copies = False
        name = __package__
        if name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            if prefs and hasattr(prefs, 'copy_on_export'):
                copies = prefs.copy_on_export

        if self.file_count == 0:
            self.report({'ERROR'}, "NOTHING TO EXPORT")
        elif copies and settings.copy_on_export:
            self.report({'INFO'}, f"Exported {self.file_count} file(s),\nMade {self.copy_count} copies")
        elif self.file_count:
            self.report({'INFO'}, f"Exported {self.file_count} file(s)")

        return {'FINISHED'}

    # Finds all renderable objects and returns a list of them
    def get_renderable_objects(self):
        """
        Recursively collect hidden objects from scene collections.
        
        Returns:
            list: A list of objects hidden in viewport or render
        """
        renderable_objects = []
        
        def check_collection(collection):
            # Skip if collection is None
            if not collection:
                return
            
            # Skip if the entire collection is hidden in render
            if collection.hide_render:
                return
            
            # Check objects in this collection
            for obj in collection.objects:
                # Check both viewport and render visibility
                if not obj.hide_render:
                    renderable_objects.append(obj)
            
            # Recursively check child collections
            while collection.children:
                for child_collection in collection.children:
                    # Skip child collections that are hidden in render
                    if not child_collection.hide_render:
                        check_collection(child_collection)
                break  # Use break to match the while loop structure
        
        # Start the recursive check from the scene's root collection
        check_collection(bpy.context.scene.collection)
        
        return renderable_objects

    # Deselect and Get Objects to Export by Limit Settings
    def get_filtered_objects(self, context, settings):
        objects = context.view_layer.objects.values()
        if settings.limit == 'VISIBLE':
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                if obj.visible_get() and obj.type in settings.object_types:
                    filtered_objects.append(obj)
            return filtered_objects
        if settings.limit == 'SELECTED':
            selection = context.selected_objects
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                if obj in selection:
                    if obj.type in settings.object_types:
                        filtered_objects.append(obj)
            return filtered_objects
        if settings.limit == 'RENDERABLE':
            filtered_objects = []
            for obj in objects:
                obj.select_set(False)
                if obj.visible_get() and obj.type in settings.object_types:
                    if obj in self.get_renderable_objects():
                        filtered_objects.append(obj)
            return filtered_objects
        return objects

    def select_children_recursive(self, obj, context):
        for c in obj.children:
            if obj.type in context.scene.batch_export.object_types:
                c.select_set(True)
            self.select_children_recursive(c, context)

    def export_selection(self, itemname, context, base_dir):
        settings = context.scene.batch_export
        # save the transform to be reset later:
        old_locations = []
        old_rotations = []
        old_scales = []
        
        # Extra objects for LOD export store for later removal
        preLodObjects = []
        lodObjects = []

        objectsloop = context.selected_objects
        for obj in objectsloop:
            # Save Old Locations
            old_locations.append(obj.location.copy())
            old_rotations.append(obj.rotation_euler.copy())
            old_scales.append(obj.scale.copy())

            # If exporting by parent, don't set child (object that has a parent) transform
            if "PARENT" in settings.mode and obj.parent in context.selected_objects:
                continue
            else:
                if settings.set_location:
                    obj.location = settings.location
                if settings.set_rotation:
                    obj.rotation_euler = settings.rotation
                if settings.set_scale:
                    obj.scale = settings.scale

            # Change Itemname If Collection As Prefix
            if settings.prefix_collection and 'OBJECT' in settings.mode:
                collection_name = obj.users_collection[0].name
                if not collection_name == 'Scene Collection':
                    itemname = "_".join([collection_name, itemname])

            # LOD Creation
            if settings.create_lod and settings.file_format == 'FBX' and obj.type == 'MESH':
                # Save obj info and backup
                obj_CollectionObjs = obj.users_collection[0].objects
                name = obj.name
                obj.name = name + '_preLOD'
                preLodObjects.append(obj)
                obj.select_set(False)

                # Setup LOD parent object
                lodParent = bpy.data.objects.new("Empty_Name", None)
                obj_CollectionObjs.link(lodParent)
                lodParent.location = obj.location
                lodParent.rotation_quaternion = obj.rotation_quaternion
                lodParent.name = name
                lodParent["fbx_type"] = "LodGroup"
                if obj.parent:
                    lodParent.parent = obj.parent
                lodObjects.append(lodParent)
                lodParent.select_set(True)

                # Create LOD0 copy
                lod0 = obj.copy()
                lod0.data = lod0.data.copy() # linked = false
                lod0.name = name + f"_LOD0"
                lod0.parent = lodParent
                lod0.location = (0,0,0)
                obj_CollectionObjs.link(lod0)
                lodObjects.append(lod0)
                lod0.select_set(True)

                # Loop over and create each LOD object
                for lodcount in range(settings.lod_count):
                    lod = lod0.copy()
                    lod.data = lod.data.copy() # linked = false
                    lod.name = name + f"_LOD{lodcount+1}"
                    lod.parent = lodParent
                    obj_CollectionObjs.link(lod)
                    lodObjects.append(lod)
                    lod.select_set(True)

                    # Decimation
                    decimate_mod = lod.modifiers.new('lodding', type='DECIMATE')
                    ratio_attr_name = f"lod{lodcount+1}_ratio"
                    decimate_mod.ratio = getattr(settings, ratio_attr_name)
                    
                    #bpy.ops.object.modifier_apply(modifier=decimate_mod.name)
                settings.apply_mods = True
                # THIS DOESNT WORK settings.object_types.EMPTY = True

        # Final File Name
        prefix = settings.prefix
        # Check Prefix for Subdirectories
        prefixroot = os.path.dirname( os.path.join(base_dir, prefix) )
        if not os.path.exists(prefixroot):
            try:
                os.makedirs(prefixroot)
                print(f"Directory created: {prefixroot}")
            except OSError as e:
                self.report({'ERROR'}, f"Error creating directory {prefixroot}: {e}")
        suffix = settings.suffix
        name = prefix + bpy.path.clean_name(itemname) + suffix
        fp = os.path.join(base_dir, name)
        extension = None
        
        # Export

        if settings.file_format == "ABC":
            extension = '.abc'
            options = utils.load_operator_preset(
                'wm.alembic_export', settings.abc_preset)
            options["filepath"] = fp+extension
            options["selected"] = True
            options["start"] = settings.frame_start
            options["end"] = settings.frame_end
            # By default, alembic_export operator runs in the background, this messes up batch
            # export though. alembic_export has an "as_background_job" arg that can be set to
            # false to disable it, but its marked deprecated, saying that if you EXECUTE the
            # operator rather than INVOKE it it runs in the foreground. Here I change the
            # execution context to EXEC_REGION_WIN.
            # docs.blender.org/api/current/bpy.ops.html?highlight=exec_default#execution-context
            bpy.ops.wm.alembic_export('EXEC_REGION_WIN', **options)

        elif settings.file_format == "USD":
            extension = settings.usd_format
            options = utils.load_operator_preset(
                'wm.usd_export', settings.usd_preset)
            options["filepath"] = fp+extension
            options["selected_objects_only"] = True
            bpy.ops.wm.usd_export(**options)

        elif settings.file_format == "SVG":
            extension = '.svg'
            bpy.ops.wm.gpencil_export_svg(
                filepath=fp+extension, selected_object_type='SELECTED')

        elif settings.file_format == "PDF":
            extension = '.pdf'
            bpy.ops.wm.gpencil_export_pdf(
                filepath=fp+extension, selected_object_type='SELECTED')

        elif settings.file_format == "OBJ":
            extension = '.obj'
            options = utils.load_operator_preset(
                'wm.obj_export', settings.obj_preset)
            options["filepath"] = fp+extension
            options["export_selected_objects"] = True
            options["apply_modifiers"] = settings.apply_mods
            bpy.ops.wm.obj_export(**options)

        elif settings.file_format == "PLY":
            extension = '.ply'
            bpy.ops.wm.ply_export(
                filepath=fp+extension, ascii_format=settings.ply_ascii, export_selected_objects=True, apply_modifiers=settings.apply_mods)

        elif settings.file_format == "STL":
            extension = '.stl'
            bpy.ops.wm.stl_export(
                filepath=fp+extension, ascii_format=settings.stl_ascii, export_selected_objects=True, apply_modifiers=settings.apply_mods)

        elif settings.file_format == "FBX":
            extension = '.fbx'
            options = utils.load_operator_preset(
                'export_scene.fbx', settings.fbx_preset)
            options["filepath"] = fp+extension
            options["use_selection"] = True
            options["use_mesh_modifiers"] = settings.apply_mods
            bpy.ops.export_scene.fbx(**options)

            # LOD De-Creation
            if settings.create_lod:
                for lod in lodObjects:
                    bpy.data.objects.remove(lod, do_unlink=True)
                for obj in preLodObjects:
                    if '_preLOD' in obj.name:
                        obj.name = obj.name[0:-7]
                        

        elif settings.file_format == "glTF":
            extension = '.glb'
            options = utils.load_operator_preset(
                'export_scene.gltf', settings.gltf_preset)
            options["filepath"] = fp
            options["use_selection"] = True
            options["export_apply"] = settings.apply_mods
            bpy.ops.export_scene.gltf(**options)
            print(options.keys())

        # Reset the transform to what it was before
        i = 0
        for obj in context.selected_objects:
            obj.location = old_locations[i]
            obj.rotation_euler = old_rotations[i]
            obj.scale = old_scales[i]
            i += 1

        print("exported: ", fp + extension)
        self.file_count += 1

        # COPY EXPORTED FILES
        copies = False
        name = __package__
        if name in context.preferences.addons:
            prefs = context.preferences.addons[name].preferences
            if prefs and hasattr(prefs, 'copy_on_export'):
                copies = prefs.copy_on_export

        if copies and settings.copy_on_export:
            exportfile = Path(fp).with_suffix(extension)
            if exportfile.exists():
                oldroot = Path(bpy.path.abspath(settings.directory))
                newroot = Path(bpy.path.abspath(settings.copy_directory))
                if not oldroot.resolve() == newroot.resolve():
                    subpath = exportfile.relative_to(oldroot)
                    copyfile = newroot / subpath

                    shutil.copy(exportfile, copyfile)
                    print('made this copy:   ', copyfile.resolve())
                    self.copy_count += 1


import bpy
import shutil
from pathlib import Path
from contextlib import contextmanager
from bpy.types import Operator
from . import utils

class EXPORT_MESH_OT_batch(Operator):
    """Export many objects to separate files all at once."""
    bl_idname = "export_mesh.batch"
    bl_label = "Batch Export"

    def execute(self, context):
        """
        Main entry point. Orchestrates the validation, job creation,
        and execution of the batch export process.
        """
        self.file_count = 0
        self.copy_count = 0
        self.collider_count = 0
        self.lod_file_count = 0
        settings = context.scene.batch_export
        prefs = context.preferences.addons[__package__].preferences

        if settings.file_format == 'FBX':
            lod_suffix = settings.lod_file_suffix.strip()
            collider_suffix = settings.collider_suffix.strip()
            if settings.create_lod and not lod_suffix:
                self.report({'ERROR'}, "LOD File Suffix cannot be empty.")
                return {'CANCELLED'}
            if settings.create_collider and not collider_suffix:
                self.report({'ERROR'}, "Collider Suffix cannot be empty.")
                return {'CANCELLED'}
            if (
                settings.create_lod
                and settings.create_collider
                and lod_suffix.casefold() == collider_suffix.casefold()
            ):
                self.report({'ERROR'}, "LOD and Collider suffixes must be different.")
                return {'CANCELLED'}

        # 1. Resolve Base Directory
        # Determines the absolute root path for exports based on preferences.
        try:
            base_dir = self._resolve_base_dir(settings, prefs)
        except ValueError as e:
             self.report({'ERROR'}, str(e))
             return {'CANCELLED'}

        # 2. Validate prerequisites (directory existence)
        if not base_dir.is_dir():
             self.report({'ERROR'}, f"Export directory does not exist: {base_dir}")
             return {'CANCELLED'}

        # 3. Wrap the entire operation in a state preservation context manager
        with self._preserve_blender_state(context):
            
            # 4. Get a master list of objects to consider for export
            filtered_objects = self._get_filtered_objects(context, settings)
            if not filtered_objects:
                self.report({'WARNING'}, "No objects matched the filter settings.")
                return {'FINISHED'}

            # 5. Generate and process each export job based on the export mode
            try:
                # We pass the resolved base_dir to the job generator
                export_jobs = self._generate_export_jobs(settings, filtered_objects, base_dir)
                for job in export_jobs:
                    self._process_export_job(context, settings, job)
            except Exception as e:
                self.report({'ERROR'}, f"Operation failed: {e}")
                import traceback
                traceback.print_exc() # Print full error to console for debugging
                return {'CANCELLED'}

        # 6. Report the final results
        self._report_results(context, settings)
        return {'FINISHED'}

    # =================================================================
    # 1. VALIDATION AND SETUP
    # =================================================================

    def _resolve_base_dir(self, settings, prefs):
        """
        Calculates the absolute base directory. 
        Raises ValueError if the path cannot be resolved (e.g. unsaved blend file with relative path).
        """
        project_dir_raw = getattr(prefs, 'project_dir', '')
        
        if project_dir_raw:
             # If Project Directory is set, it takes precedence as the root.
             # We treat the settings.directory as relative to this project root.
             project_root = Path(bpy.path.abspath(project_dir_raw))
             
             relative_part = settings.directory
             # Remove Blender's relative prefix '//' if present so pathlib joins correctly
             if relative_part.startswith('//'):
                  relative_part = relative_part[2:]
             elif relative_part.startswith('\\'):
                  relative_part = relative_part[1:]

             return (project_root / relative_part).resolve()
        else:
             # Standard behavior: relative to .blend file
             if settings.directory.startswith('//') and not bpy.data.is_saved:
                  raise ValueError("Save the .blend file before exporting to a relative directory, or set a Project Directory in preferences.")
             
             return Path(bpy.path.abspath(settings.directory)).resolve()

    # =================================================================
    # 2. STATE MANAGEMENT (CONTEXT MANAGERS)
    # =================================================================

    @contextmanager
    def _preserve_blender_state(self, context):
        """Saves and restores selection, active object, and mode."""
        view_layer = context.view_layer
        original_selection = context.selected_objects[:]
        original_active = view_layer.objects.active
        original_mode = original_active.mode if original_active else 'OBJECT'

        try:
            if original_mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            yield
        finally:
            # This finally block ensures cleanup happens even if an error occurs during export
            if context.view_layer.objects.active and context.view_layer.objects.active.mode != 'OBJECT':
                 bpy.ops.object.mode_set(mode='OBJECT')

            bpy.ops.object.select_all(action='DESELECT')
            for obj in original_selection:
                try:
                    obj.select_set(True)
                except RuntimeError:
                     pass # Object might have been deleted during process
                     
            if original_active and original_active.name in context.view_layer.objects:
                view_layer.objects.active = original_active
                if original_mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=original_mode)

    @contextmanager
    def temporary_visibility(self, objects):
        """Temporarily makes objects and their parent hierarchies visible for export."""
        originally_hidden = set()
        objects_to_process = set(objects)
        # Ensure parents are also visible so children can be exported correctly
        for obj in objects:
            parent = obj.parent
            while parent:
                objects_to_process.add(parent)
                parent = parent.parent
        
        for obj in objects_to_process:
            if obj.hide_get():
                originally_hidden.add(obj)
                obj.hide_set(False)
        try:
            yield
        finally:
            for obj in originally_hidden:
                 # Check if object still exists before trying to hide it
                if obj and obj.name in bpy.data.objects:
                    obj.hide_set(True)

    @contextmanager
    def _temporary_transform(self, settings, objects_to_transform):
        """Applies and then resets object transforms for the duration of the export."""
        original_transforms = {
            obj: (obj.location.copy(), obj.rotation_euler.copy(), obj.scale.copy())
            for obj in objects_to_transform
        }
        
        try:
            for obj in objects_to_transform:
                # Don't apply transforms to children if we are exporting PARENT_OBJECTS,
                # otherwise double-transforms might occur depending on exporter settings.
                is_child_of_selected = "PARENT" in settings.mode and obj.parent in objects_to_transform
                if not is_child_of_selected:
                    if settings.set_location: obj.location = settings.location
                    if settings.set_rotation: obj.rotation_euler = settings.rotation
                    if settings.set_scale: obj.scale = settings.scale
            yield
        finally:
            for obj, (loc, rot, scale) in original_transforms.items():
                if obj and obj.name in bpy.data.objects:
                    obj.location, obj.rotation_euler, obj.scale = loc, rot, scale

    def _bake_mesh_object(self, context, obj):
        """Replace an object's mesh with its evaluated Blender 5.x result."""
        depsgraph = context.evaluated_depsgraph_get()
        context.view_layer.update()
        evaluated_obj = obj.evaluated_get(depsgraph)
        baked_mesh = bpy.data.meshes.new_from_object(
            evaluated_obj,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        if baked_mesh is None:
            raise RuntimeError(f"Could not evaluate modifiers for '{obj.name}'")

        previous_mesh = obj.data
        obj.data = baked_mesh
        obj.modifiers.clear()

        # LOD source meshes are private temporary copies. Ordinary export copies
        # initially share their source mesh and must never delete it.
        if previous_mesh and previous_mesh.users == 0:
            bpy.data.meshes.remove(previous_mesh)

        return baked_mesh

    @contextmanager
    def _baked_export_copies(self, context, settings, objects):
        """Bake modifiers before applying temporary export transforms.

        Exporters normally evaluate modifiers after reading object transforms.
        A temporary evaluated copy reverses that order without touching the
        source object: modifiers -> export transform -> exporter.
        """
        needs_late_transform = (
            settings.apply_mods
            and (settings.set_location or settings.set_rotation or settings.set_scale)
        )
        if not needs_late_transform:
            yield objects
            return

        temporary_objects = []
        baked_meshes = []
        renamed_sources = []
        object_map = {}

        try:
            for source in objects:
                if source.type != 'MESH':
                    object_map[source] = source
                    continue

                source_name = source.name
                source.name = f"{source_name}__SDBE_SOURCE"
                renamed_sources.append((source, source_name))

                export_copy = source.copy()
                export_copy.name = source_name
                collection = source.users_collection[0] if source.users_collection else context.scene.collection
                collection.objects.link(export_copy)
                temporary_objects.append(export_copy)
                object_map[source] = export_copy

            # Preserve hierarchies when both parent and child are part of a job.
            for source, export_object in object_map.items():
                if export_object is source:
                    continue
                export_object.parent = object_map.get(source.parent, source.parent)

            # All copies still have their original transforms here, so modifiers
            # that depend on world/object coordinates evaluate correctly.
            for export_object in temporary_objects:
                baked_meshes.append(self._bake_mesh_object(context, export_object))

            yield [object_map[obj] for obj in objects]

        finally:
            for export_object in temporary_objects:
                if export_object and export_object.name in bpy.data.objects:
                    bpy.data.objects.remove(export_object, do_unlink=True)
            for mesh in baked_meshes:
                if mesh and mesh.name in bpy.data.meshes and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            for source, source_name in renamed_sources:
                if source and source.name in bpy.data.objects:
                    source.name = source_name

    @contextmanager
    def _unity_axis_converted_copies(self, context, settings, objects):
        """Create a temporary, hierarchy-safe Blender-to-Unity conversion.

        Blender's FBX ``bake_space_transform`` can accumulate incorrect local
        transforms in nested Mesh/Empty hierarchies. Convert both object-local
        matrices and mesh data explicitly, then ask FBX to write those values
        unchanged while merely declaring the target axes.
        """
        if settings.file_format != 'FBX' or any(
            obj.type not in {'MESH', 'EMPTY'} for obj in objects
        ):
            yield objects, False
            return

        from bpy_extras.io_utils import axis_conversion
        from mathutils import Matrix

        axis_matrix = axis_conversion(
            from_forward='Y',
            from_up='Z',
            to_forward='-Z',
            to_up='Y',
        ).to_4x4()
        axis_matrix_inv = axis_matrix.inverted()

        temporary_objects = []
        temporary_meshes = []
        renamed_sources = []
        object_map = {}
        context.view_layer.update()
        source_local_matrices = {
            obj: obj.matrix_local.copy() for obj in objects
        }
        source_world_matrices = {
            obj: obj.matrix_world.copy() for obj in objects
        }

        try:
            # Copy every transform node, not just meshes. Export-time axis
            # conversion must never modify the user's scene or its pivots.
            for source in objects:
                source_name = source.name
                source.name = f"{source_name}__SDBE_AXIS_SOURCE"
                renamed_sources.append((source, source_name))

                export_copy = source.copy()
                export_copy.name = source_name
                collection = (
                    source.users_collection[0]
                    if source.users_collection
                    else context.scene.collection
                )
                collection.objects.link(export_copy)
                temporary_objects.append(export_copy)
                object_map[source] = export_copy

                if source.type == 'MESH':
                    export_copy.data = source.data.copy()
                    temporary_meshes.append(export_copy.data)

            # Evaluate modifiers before changing coordinate systems. Applying
            # object-space modifiers after the conversion could change their
            # meaning and produce different geometry.
            if settings.apply_mods:
                for source, export_copy in object_map.items():
                    if source.type == 'MESH':
                        previous_mesh = export_copy.data
                        baked_mesh = self._bake_mesh_object(context, export_copy)
                        if previous_mesh in temporary_meshes:
                            temporary_meshes.remove(previous_mesh)
                        temporary_meshes.append(baked_mesh)

            # Rebuild only relationships that belong to this export job. A
            # job root is intentionally detached from non-exported parents and
            # receives its converted world matrix.
            for source, export_copy in object_map.items():
                # Freeze the already captured/evaluated transform. Constraints,
                # animation and delta channels must not re-apply themselves to
                # the converted matrix on the next dependency-graph update.
                export_copy.animation_data_clear()
                export_copy.constraints.clear()
                export_copy.delta_location = (0.0, 0.0, 0.0)
                export_copy.delta_rotation_euler = (0.0, 0.0, 0.0)
                export_copy.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                export_copy.delta_scale = (1.0, 1.0, 1.0)

                export_parent = object_map.get(source.parent)
                export_copy.parent = export_parent
                export_copy.matrix_parent_inverse = Matrix.Identity(4)

                source_matrix = (
                    source_local_matrices[source]
                    if export_parent
                    else source_world_matrices[source]
                )
                converted_matrix = (
                    axis_matrix @ source_matrix @ axis_matrix_inv
                )
                if export_parent:
                    export_copy.matrix_basis = converted_matrix
                else:
                    export_copy.matrix_world = converted_matrix

            # Geometry uses a one-sided basis conversion. Together with the
            # conjugated node matrix this preserves the exact world-space
            # result: (C M C^-1) (C v) = C (M v).
            for source, export_copy in object_map.items():
                if source.type == 'MESH':
                    export_copy.data.transform(axis_matrix, shape_keys=True)
                    export_copy.data.update()

            context.view_layer.update()
            yield [object_map[obj] for obj in objects], True

        finally:
            for export_copy in temporary_objects:
                if export_copy and export_copy.name in bpy.data.objects:
                    bpy.data.objects.remove(export_copy, do_unlink=True)
            for mesh in temporary_meshes:
                if mesh and mesh.name in bpy.data.meshes and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            for source, source_name in renamed_sources:
                if source and source.name in bpy.data.objects:
                    source.name = source_name

    @contextmanager
    def _managed_lods(self, context, settings, obj):
        """Create, evaluate and clean up an FBX LOD hierarchy."""
        # Exit early if not applicable
        if not (settings.create_lod and settings.file_format == 'FBX' and obj.type == 'MESH'):
            yield [obj]
            return

        lod_objects = []
        original_name = obj.name
        original_parent = obj.parent
        
        try:
            # 1. Rename original to prevent name collisions and indicate it's NOT the export target
            obj.name = f"{original_name}_preLOD"
            
            # 2. Create LOD Group Parent (Empty)
            # We link it to the same collection as the source object
            collection = obj.users_collection[0]
            lod_parent = bpy.data.objects.new(original_name, None)
            collection.objects.link(lod_parent)
            
            # FBX specific custom property for recognized LODs
            lod_parent["fbx_type"] = "LodGroup"
            if original_parent:
                lod_parent.parent = original_parent
            lod_parent.matrix_world = obj.matrix_world.copy()
                
            lod_objects.append(lod_parent)
            
            # 3. Create LOD0 (The active mesh, parented to the LOD group)
            lod0 = obj.copy()
            lod0.data = lod0.data.copy()
            lod0.name = f"{original_name}_LOD0"
            collection.objects.link(lod0)

            if not settings.apply_mods:
                lod0.modifiers.clear()
            
            # Parent to LOD group and zero out local transforms
            lod0.parent = lod_parent
            lod0.matrix_local.identity() 
            
            lod_objects.append(lod0)
            
            # 4. Create subsequent generated LODs
            for i in range(settings.lod_count):
                lod_ratio = getattr(settings, f"lod{i + 1}_ratio")
                # Skip if ratio is 1.0 (no reduction needed, saves processing)
                if lod_ratio >= 1.0: continue

                lod = lod0.copy()
                lod.data = lod.data.copy()
                lod.name = f"{original_name}_LOD{i + 1}"
                collection.objects.link(lod)
                lod.parent = lod_parent
                lod.matrix_local.identity()
                
                mod = lod.modifiers.new(name='DecimateLOD', type='DECIMATE')
                mod.ratio = lod_ratio
                if settings.lod_modifier_order == 'BEFORE_MODIFIERS':
                    lod.modifiers.move(len(lod.modifiers) - 1, 0)
                lod_objects.append(lod)

            # Bake the stack at the original object transform. Decimate is
            # always baked so LOD remains functional even when Apply Modifiers
            # is disabled; existing modifiers were removed above in that case.
            for lod_obj in lod_objects[1:]:
                if lod_obj.type == 'MESH' and lod_obj.modifiers:
                    self._bake_mesh_object(context, lod_obj)

            yield lod_objects

        finally:
            # Guaranteed cleanup of temporary objects
            for lod_obj in lod_objects:
                if lod_obj and lod_obj.name in bpy.data.objects:
                    mesh = lod_obj.data if lod_obj.type == 'MESH' else None
                    bpy.data.objects.remove(lod_obj, do_unlink=True)
                    if mesh and mesh.name in bpy.data.meshes and mesh.users == 0:
                        bpy.data.meshes.remove(mesh)
            
            # Restore original object name
            if obj and obj.name in bpy.data.objects:
                obj.name = original_name

    @contextmanager
    def _managed_collider(self, context, settings, objects):
        """Create simplified temporary meshes for a separate Unity collider FBX."""
        collider_objects = []
        collider_meshes = []
        object_map = {}

        try:
            for source in objects:
                if source.type != 'MESH':
                    continue

                collider = source.copy()
                collider.name = f"{source.name}{settings.collider_suffix}"
                collection = source.users_collection[0] if source.users_collection else context.scene.collection
                collection.objects.link(collider)

                # Apply Modifiers controls whether the source stack participates
                # in collider generation. Collider Decimate itself is always baked.
                if not settings.apply_mods:
                    collider.modifiers.clear()

                decimate = collider.modifiers.new(name='ColliderDecimate', type='DECIMATE')
                decimate.ratio = settings.collider_ratio

                collider_objects.append(collider)
                object_map[source] = collider

            # Recreate parent relationships when a batch job contains a hierarchy.
            for source, collider in object_map.items():
                collider.parent = object_map.get(source.parent, source.parent)

            # Evaluation happens at the original transforms. Export transforms
            # are applied only after this context manager yields the baked meshes.
            for collider in collider_objects:
                collider_meshes.append(self._bake_mesh_object(context, collider))

            yield collider_objects

        finally:
            for collider in collider_objects:
                if collider and collider.name in bpy.data.objects:
                    bpy.data.objects.remove(collider, do_unlink=True)
            for mesh in collider_meshes:
                if mesh and mesh.name in bpy.data.meshes and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)

    # =================================================================
    # 3. OBJECT GATHERING AND JOB CREATION
    # =================================================================

    def _get_filtered_objects(self, context, settings):
        """Gets a list of all objects that meet the initial filter criteria."""
        source_objects = []
        if settings.limit == 'SELECTED':
            source_objects = context.selected_objects[:]

            # In a parent export, selecting a hierarchy root means exporting
            # that hierarchy. This also gives us the structural Empties needed
            # to preserve pivots even when EMPTY is not enabled as a standalone
            # object type in the UI.
            if "PARENT" in settings.mode:
                expanded_objects = []
                seen_objects = set()
                for root in source_objects:
                    for obj in (root, *root.children_recursive):
                        if obj not in seen_objects:
                            seen_objects.add(obj)
                            expanded_objects.append(obj)
                source_objects = expanded_objects
        elif settings.limit == 'VISIBLE':
            source_objects = [obj for obj in context.view_layer.objects if obj.visible_get()]
        elif settings.limit == 'RENDERABLE':
            # Get all objects that will actually render
            renderable_names = {obj.name for obj in self._get_all_renderable_objects(context.scene)}
            source_objects = [obj for obj in context.view_layer.objects if obj.name in renderable_names]
        else: # 'ALL' in view layer
             # Using view_layer.objects instead of scene.objects ensures we only get objects
             # currently instantiated in this view layer (relevant for complex scenes)
            source_objects = context.view_layer.objects[:]
            
        # Further filter by object types specified in settings.
        filtered_objects = [
            obj for obj in source_objects if obj.type in settings.object_types
        ]

        if "PARENT" not in settings.mode:
            return filtered_objects

        # Empties in an exported parent chain are transforms/pivots, not
        # optional content. Omitting one changes every descendant's local
        # coordinate system and is especially visible after Blender-to-Unity
        # axis conversion. Include only structural Empty ancestors; the EMPTY
        # type checkbox still controls unrelated/standalone Empties.
        filtered_set = set(filtered_objects)
        structural_empties = []
        for obj in filtered_objects:
            parent = obj.parent
            while parent:
                if parent.type == 'EMPTY' and parent not in filtered_set:
                    filtered_set.add(parent)
                    structural_empties.append(parent)
                parent = parent.parent

        return filtered_objects + structural_empties

    def _get_all_renderable_objects(self, scene):
        """
        Recursively finds all objects that are NOT hidden from render.
        Handles complex collection visibility hierarchies.
        """
        renderable = []
        # We temporarily make everything visible in viewport to accurately check
        # 'hide_render' status if it relies on drivers or complex states,
        # though usually hide_render is independent.
        # The safer approach is just recursive checking without forcing viewport vis:
        
        def is_collection_renderable(col):
             if col.hide_render: return False
             # Recurse up to ensure no parent collection is hidden
             # (Blender doesn't always strictly enforce this in standard API but good practice)
             return True

        def check_collection(collection):
            if collection.hide_render: return
            
            for obj in collection.objects:
                if not obj.hide_render:
                    renderable.append(obj)
            
            for child in collection.children:
                check_collection(child)

        check_collection(scene.collection)
        return renderable

    def _generate_export_jobs(self, settings, objects, base_dir):
        """A generator that yields a 'job' dictionary for each file to be exported."""
        mode = settings.mode
        
        if mode == 'OBJECTS' or ('COLLECTION_SUBDIR' in mode and 'PARENT' not in mode):
            for obj in objects:
                yield self._create_job(settings, obj.name, [obj], base_dir, source_obj=obj)

        elif mode == 'PARENT_OBJECTS' or ('COLLECTION_SUBDIR' in mode and 'PARENT' in mode):
            # Convert to set for fast lookups
            object_set = set(objects)
            for obj in objects:
                # If this object's parent is ALSO in the selection list, skip it.
                # We only want to generate jobs for the top-most parents in the selection.
                if obj.parent in object_set:
                     continue

                # Gather all descendents that are also in the filter list
                # (children_recursive gives all nested children)
                children_to_export = [c for c in obj.children_recursive if c in object_set]
                yield self._create_job(settings, obj.name, [obj] + children_to_export, base_dir, source_obj=obj)
        
        elif mode == 'COLLECTIONS':
            # Group objects by their primary collection
            collections_to_export = {}
            for obj in objects:
                if obj.users_collection:
                    # Objects can be in multiple collections; we take the first one as primary
                    primary_coll = obj.users_collection[0]
                    collections_to_export.setdefault(primary_coll, []).append(obj)
            
            for coll, coll_objects in collections_to_export.items():
                yield self._create_job(settings, coll.name, coll_objects, base_dir)
        
        elif mode == 'SCENE':
            filename = settings.prefix + settings.suffix
            # If no prefix/suffix, fallback to blend file name
            if not filename:
                filename = Path(bpy.data.filepath).stem if bpy.data.is_saved else "Untitled"
            yield self._create_job(settings, filename, objects, base_dir)

    def _create_job(self, settings, name, objects, base_dir, source_obj=None):
        """Helper to build a job dictionary, handling subdirectories and prefixes."""
        job_dir = base_dir
        item_name = name
        
        # Handle collection subdirectories if enabled
        if 'COLLECTION_SUBDIR' in settings.mode and source_obj and source_obj.users_collection:
            collection = source_obj.users_collection[0]
            if collection.name != "Scene Collection":
                if settings.full_hierarchy:
                    # This assumes 'utils.get_collection_hierarchy' exists as in original code
                    hierarchy = utils.get_collection_hierarchy(collection.name)
                    job_dir = base_dir / hierarchy
                else:
                    job_dir = base_dir / collection.name
                
                # Create the subdirectory immediately so it exists for export
                job_dir.mkdir(parents=True, exist_ok=True)
        
        # Handle collection prefixing if enabled
        if settings.prefix_collection and 'OBJECT' in settings.mode and source_obj and source_obj.users_collection:
            collection_name = source_obj.users_collection[0].name
            if collection_name != 'Scene Collection':
                item_name = f"{collection_name}_{item_name}"

        return {'name': item_name, 'objects': objects, 'directory': job_dir}

    # =================================================================
    # 4. CORE EXPORT PROCESSING
    # =================================================================

    def _process_export_job(self, context, settings, job):
        """Executes a single export job with robust state management."""
        if not job['objects']:
            return

        # Deselect everything first to ensure clean state for this job
        bpy.ops.object.select_all(action='DESELECT')

        # Use nested context managers for maximum safety during temporary changes
        try:
            # 1. Ensure objects are visible (needed for some exporters)
            with self.temporary_visibility(job['objects']):
                is_lod_job = settings.create_lod and settings.file_format == 'FBX'
                single_mesh = len(job['objects']) == 1 and job['objects'][0].type == 'MESH'

                if is_lod_job and single_mesh:
                    if settings.export_default_with_lods:
                        self._export_standard_job(context, settings, job)

                    # The LOD hierarchy is exported to its own suffixed FBX.
                    with self._managed_lods(context, settings, job['objects'][0]) as lod_objects:
                        # Only the LOD group root receives the transform. Its
                        # children use identity local matrices.
                        with self._temporary_transform(settings, [lod_objects[0]]):
                            self._select_and_export(
                                settings,
                                job,
                                lod_objects,
                                filename_suffix=settings.lod_file_suffix,
                                is_lod_file=True,
                            )
                else:
                    self._export_standard_job(context, settings, job)

                if settings.file_format == 'FBX' and settings.create_collider:
                    self._export_collider_job(context, settings, job)

        finally:
            # Ensure everything is deselected after the job completes
            bpy.ops.object.select_all(action='DESELECT')

    def _export_standard_job(self, context, settings, job):
        """Export the regular, non-LOD representation of an export job."""
        with self._baked_export_copies(context, settings, job['objects']) as objects_to_export:
            # Modifier evaluation above is complete; transforms are deliberately
            # the last geometry-affecting step.
            with self._temporary_transform(settings, objects_to_export):
                self._select_and_export(settings, job, objects_to_export)

    def _select_and_export(
        self,
        settings,
        job,
        objects_to_export,
        filename_suffix="",
        is_lod_file=False,
    ):
        """Helper to select the specific objects for this job and trigger export."""
        with self._unity_axis_converted_copies(
            bpy.context, settings, objects_to_export
        ) as (final_objects, axes_preconverted):
            bpy.ops.object.select_all(action='DESELECT')
            # Select only the objects for this specific job
            for obj in final_objects:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if final_objects:
                bpy.context.view_layer.objects.active = final_objects[0]

            # Run the actual Blender operator
            filepath = self._dispatch_export_operator(
                settings,
                job,
                filename_suffix,
                axes_preconverted=axes_preconverted,
            )

        if filepath:
            self.file_count += 1
            if is_lod_file:
                self.lod_file_count += 1
            print(f"Exported: {filepath}")
            # Perform the optional copy
            self._copy_exported_file(settings, filepath)

    def _export_collider_job(self, context, settings, job):
        """Export one simplified collider FBX alongside the visual FBX."""
        with self._managed_collider(context, settings, job['objects']) as collider_objects:
            if not collider_objects:
                return

            bpy.ops.object.select_all(action='DESELECT')
            with self._temporary_transform(settings, collider_objects):
                for collider in collider_objects:
                    collider.select_set(True)
                context.view_layer.objects.active = collider_objects[0]

                filename = (
                    settings.prefix
                    + bpy.path.clean_name(job['name'])
                    + settings.suffix
                    + settings.collider_suffix
                )
                filepath_no_ext = job['directory'] / filename
                filepath = self.export_fbx(settings, str(filepath_no_ext))

                if filepath:
                    self.collider_count += 1
                    print(f"Exported collider: {filepath}")
                    self._copy_exported_file(settings, filepath)

    def _dispatch_export_operator(
        self,
        settings,
        job,
        filename_suffix="",
        axes_preconverted=False,
    ):
        """Calls the appropriate Blender export operator based on settings."""
        prefix = settings.prefix
        suffix = settings.suffix
        # Clean the name to ensure it's valid for a file system
        clean_name = prefix + bpy.path.clean_name(job['name']) + suffix + filename_suffix
        filepath_no_ext = job['directory'] / clean_name
        
        # Map format enums to their handler functions
        DISPATCHER = {
            "FBX": self.export_fbx,
            "glTF": self.export_gltf,
            "ABC": self.export_alembic,
            "USD": self.export_usd,
            "SVG": self.export_svg,
            "PDF": self.export_pdf,
            "OBJ": self.export_obj,
            "PLY": self.export_ply,
            "STL": self.export_stl,
        }

        handler = DISPATCHER.get(settings.file_format)
        if handler:
             # Execute the specific export function
             if settings.file_format == 'FBX':
                 return handler(
                     settings,
                     str(filepath_no_ext),
                     axes_preconverted=axes_preconverted,
                 )
             return handler(settings, str(filepath_no_ext))
        return None

    # =================================================================
    # 5. POST-PROCESSING AND REPORTING
    # =================================================================

    def _copy_exported_file(self, settings, exported_file_path):
        """Copies the exported file to a secondary directory if enabled."""
        # Re-read prefs to ensure we have latest state
        prefs = bpy.context.preferences.addons[__package__].preferences
        should_copy = prefs.copy_on_export and settings.copy_on_export
        
        if not should_copy: return

        exported_path = Path(exported_file_path)
        if not exported_path.exists(): return
            
        try:
            # Calculate the relative path from the main export root
            # This maintains subdirectory structures in the copy location
            main_export_root = self._resolve_base_dir(settings, prefs)
            
            try:
                relative_path = exported_path.relative_to(main_export_root)
            except ValueError:
                # Fallback if it wasn't relative for some reason, just use filename
                relative_path = exported_path.name

            dest_root = Path(bpy.path.abspath(settings.copy_directory)).resolve()
            copy_path = dest_root / relative_path
            
            # Ensure destination subdirectory exists
            copy_path.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy(exported_path, copy_path)
            self.copy_count += 1
            print(f"Copied to: {copy_path}")
        except Exception as e:
            print(f"Copy failed: {e}")

    def _report_results(self, context, settings):
        """Generates the final report message for the user."""
        prefs = context.preferences.addons[__package__].preferences
        copies_enabled = prefs.copy_on_export and settings.copy_on_export

        if self.file_count == 0:
            self.report({'WARNING'}, "Operation complete. No files were exported.")
        elif copies_enabled and self.copy_count > 0:
            self.report({'INFO'}, f"Exported {self.file_count} mesh file(s), {self.lod_file_count} LOD file(s), {self.collider_count} collider(s), and made {self.copy_count} copies.")
        elif self.collider_count > 0:
            self.report({'INFO'}, f"Exported {self.file_count} mesh file(s), {self.lod_file_count} LOD file(s), and {self.collider_count} collider(s).")
        elif self.lod_file_count > 0:
            self.report({'INFO'}, f"Exported {self.file_count} mesh file(s), including {self.lod_file_count} LOD file(s).")
        else:
            self.report({'INFO'}, f"Successfully exported {self.file_count} file(s).")


    # --- Individual Export Wrappers ---
    # These standardize calling the various Blender operators.
    # They return the final full filepath (with extension) on success.

    def export_fbx(self, settings, filepath_no_ext, axes_preconverted=False):
        """FBX export with Unity orientation and true meter scale."""
        import bpy

        ext = '.fbx'
        full_path = filepath_no_ext + ext

        options = utils.load_operator_preset('export_scene.fbx', settings.fbx_preset)
        options.update({
            "filepath": full_path,
            "use_selection": True,
            # Selection has already been filtered by this add-on. Keep every
            # supported selected node type enabled here so an FBX preset cannot
            # silently remove structural Empty pivots from the hierarchy.
            "object_types": {
                'EMPTY', 'MESH', 'OTHER', 'ARMATURE', 'CAMERA', 'LIGHT'
            },
            "use_mesh_modifiers": settings.apply_mods,
            # ✅ метрична система без масштабування
            "global_scale": 1.0,
            "apply_unit_scale": False,
            "apply_scale_options": 'FBX_SCALE_ALL',
            # Unity orientation. Mesh/Empty jobs are converted explicitly on
            # temporary copies, which avoids Blender's nested Apply Transform
            # bug while retaining clean zero rotations in Unity. Unsupported
            # object types keep Blender's native fallback.
            "axis_forward": '-Z',
            "axis_up": 'Y',
            "use_space_transform": not axes_preconverted,
            "bake_space_transform": not axes_preconverted,
        })

        print("✅ Exporting FBX (Unity orientation + meter scale)")
        bpy.ops.export_scene.fbx(**options)
        print(f"✅ Exported FBX: {full_path}")
        return full_path

    
    def export_gltf(self, settings, filepath_no_ext):
        # glTF exporter automatically adds extension based on format if not present,
        # but safer to be explicit if we know we want GLB.
        ext = '.glb' 
        full_path = filepath_no_ext + ext
        options = utils.load_operator_preset('export_scene.gltf', settings.gltf_preset)
        options.update({
            "filepath": full_path,
            "export_format": 'GLB', # Forcing GLB as standard, could be made an option
            "use_selection": True,
            "export_apply": settings.apply_mods
        })
        bpy.ops.export_scene.gltf(**options)
        return full_path
        
    def export_alembic(self, settings, filepath_no_ext):
        ext = '.abc'
        full_path = filepath_no_ext + ext
        options = utils.load_operator_preset('wm.alembic_export', settings.abc_preset)
        options.update({
            "filepath": full_path,
            "selected": True,
            "start": settings.frame_start,
            "end": settings.frame_end
        })
        bpy.ops.wm.alembic_export('EXEC_DEFAULT', **options)
        return full_path
    
    def export_usd(self, settings, filepath_no_ext):
        ext = settings.usd_format
        full_path = filepath_no_ext + ext
        options = utils.load_operator_preset('wm.usd_export', settings.usd_preset)
        options.update({
            "filepath": full_path,
            "selected_objects_only": True
        })
        bpy.ops.wm.usd_export(**options)
        return full_path
    
    def export_svg(self, settings, filepath_no_ext):
        ext = '.svg'
        full_path = filepath_no_ext + ext
        bpy.ops.wm.gpencil_export_svg(filepath=full_path, selected_object_type='SELECTED')
        return full_path
    
    def export_pdf(self, settings, filepath_no_ext):
        ext = '.pdf'
        full_path = filepath_no_ext + ext
        bpy.ops.wm.gpencil_export_pdf(filepath=full_path, selected_object_type='SELECTED')
        return full_path
    
    def export_obj(self, settings, filepath_no_ext):
        ext = '.obj'
        full_path = filepath_no_ext + ext
        options = utils.load_operator_preset('wm.obj_export', settings.obj_preset)
        options.update({
            "filepath": full_path,
            "export_selected_objects": True,
            "apply_modifiers": settings.apply_mods
        })
        bpy.ops.wm.obj_export(**options)
        return full_path
    
    def export_ply(self, settings, filepath_no_ext):
        ext = '.ply'
        full_path = filepath_no_ext + ext
        bpy.ops.wm.ply_export(
            filepath=full_path, 
            ascii_format=settings.ply_ascii, 
            export_selected_objects=True, 
            apply_modifiers=settings.apply_mods
        )
        return full_path
    
    def export_stl(self, settings, filepath_no_ext):
        ext = '.stl'
        full_path = filepath_no_ext + ext
        bpy.ops.wm.stl_export(
            filepath=full_path, 
            ascii_format=settings.stl_ascii, 
            export_selected_objects=True, 
            apply_modifiers=settings.apply_mods
        )
        return full_path

registry = [
    EXPORT_MESH_OT_batch,
]
