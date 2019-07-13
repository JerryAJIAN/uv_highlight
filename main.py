import time

import bpy
import bmesh
from bpy.app.handlers import persistent

import numpy as np
import math
import mathutils

from mathutils import Matrix, Vector
from collections import defaultdict

from . import render
from . import mesh


class Updater():
    '''
    This is the main updater, it hooks up the depsgraph handler (which in turn starts
    a never ending modal timer) and stores the need for updates whenever something changed via the depsgraph.
    The heartbeat does then all the necessary refreshes of the data, and finally updates the renderers.
    '''

    def __init__(self, renderer_view3d, renderer_uv):
        self.renderer_view3d = renderer_view3d
        self.renderer_uv = renderer_uv
        self.mouse_update = False
        self.mouse_position = (0, 0)
        self.timer_running = False
        self.uv_select_mode = "VERTEX"
        self.mesh_data = {}
        self.last_update = {}
        self.op = None
        self.uv_editor_visible = False

    def start(self):
        bpy.app.handlers.depsgraph_update_post.append(self.depsgraph_handler)

    def stop(self):
        self.renderer_uv.disable()
        self.renderer_view3d.disable()
        self.timer_running = False

        try:
            bpy.app.handlers.depsgraph_update_post.remove(
                self.depsgraph_handler)
        except Exception as e:
            pass

    def watch_mouse(self):
        bpy.ops.uv.mouseposition('INVOKE_DEFAULT')

    def get_active_objects(self):
        active_objects = {}
        for selected_obj in bpy.context.selected_objects:
            active_objects[selected_obj.name] = selected_obj
        return active_objects

    def heartbeat(self):
        self.watch_mouse()

        obj = bpy.context.active_object
        if not obj or  obj.type != 'MESH':
            return

        self.free()

        uv_select_mode = bpy.context.scene.tool_settings.uv_select_mode
        if uv_select_mode != self.uv_select_mode:
            self.uv_select_mode = uv_select_mode
            self.renderer_view3d.mode = uv_select_mode
            render.tag_redraw_all_views()

        active_objects = self.get_active_objects()

        for id in active_objects.keys():
            if id not in self.mesh_data.keys():
                self.mesh_data[id] = mesh.Data()
                self.last_update[id] = -1

        if self.handle_uv_edtitor_visibility_changed(active_objects):       
            return
        
       
        if self.handle_id_updates(active_objects):
            return

        if self.handle_selection_changed_ops(active_objects):
            return

    def handle_id_updates(self, active_objects):
        # print( "mesh_data: %s" % len(self.mesh_data.keys()))
        # print( "updates  : %s" % len(self.last_update.keys()))

        result = False
        t = time.perf_counter()
        for id, last_update in self.last_update.items():
            if t > last_update and last_update > 0:
                self.last_update[id] = -1

                if self.mesh_data[id].update(active_objects[id], False):
                    self.renderer_view3d.update(self.mesh_data[id])
                    self.renderer_uv.update(self.mesh_data[id])
                    render.tag_redraw_all_views()

                result = True

        return result

    def handle_selection_changed_ops(self, active_objects):
        if len(bpy.context.window_manager.operators) == 0:
            return False

        op = bpy.context.window_manager.operators[-1]
        if op != self.op:
            self.op = op
        else:
            return False

        if op.bl_idname.startswith("UV_OT_select"):
            for id, mesh_data in self.mesh_data.items():
                if mesh_data.update(active_objects[id], True):
                    self.renderer_view3d.update(mesh_data)
                    self.renderer_uv.update(mesh_data)
        
        return True

    def handle_uv_edtitor_visibility_changed(self, active_objects):
        visibility = self.uv_editor_visibility()
        if self.uv_editor_visible == visibility:
            if not self.uv_editor_visible:
                if self.renderer_view3d.enabled:
                    self.renderer_view3d.disable()
                    render.tag_redraw_all_views()                
            return False
        
        self.uv_editor_visible = visibility

        if self.uv_editor_visible:
            for id, obj in active_objects.items():
                mesh_data = self.mesh_data[id]
                if mesh_data.update(obj, False):
                    self.renderer_view3d.update(mesh_data)
                    self.renderer_uv.update(mesh_data)
                    render.tag_redraw_all_views()
        else:
            self.renderer_view3d.disable()
            render.tag_redraw_all_views()                
            
        return True
        

    def free(self):
        active_objects = self.get_active_objects()

        obsolete = []
        for id in self.mesh_data.keys():
            if id not in active_objects.keys():
                obsolete.append(id)

        for id in obsolete:
            del self.last_update[id]
            del self.mesh_data[id]

    def uv_editor_visibility(self):
        for area in bpy.context.screen.areas:
            if area.type == "IMAGE_EDITOR" and area.ui_type == "UV":
                return True
        return False

    def can_skip_depsgraph(self, update):

        if not update.id or not update.is_updated_geometry:
            return True

        if not hasattr(update.id, 'type'):
            return True

        if update.id.type != 'MESH':
            return True

        active_objects = self.get_active_objects()
        for name in active_objects.keys():
            if name == update.id.name:
                return False

        return True

    @persistent
    def depsgraph_handler(self, dummy):
        # start modal timer
        if not self.timer_running:
            self.timer_running = True
            bpy.ops.uv.timer()
            return

        depsgraph = bpy.context.evaluated_depsgraph_get()
        for update in depsgraph.updates:

            # I do not handle depsgraph updates directly, this gets deffered to the next heartbeat update.
            # Handling updates directly caused weird memory corruption crashes :/
            # ... and it's highly inefficent for updates like move.

            if self.can_skip_depsgraph(update):
                continue

            if not update.id.name in self.last_update:
                self.last_update[update.id.name] = -1

            t = time.perf_counter()
            last_update = self.last_update[update.id.name]
            if t < last_update and last_update > 0:
                self.last_update[update.id.name] = t + 0.1
            else:
                self.last_update[update.id.name] = t + 0.01


updater = Updater(render.RendererView3d(),
                  render.RendererUV())
