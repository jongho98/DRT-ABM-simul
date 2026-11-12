from urllib import request
from ..passenger import Passenger
from ..city import City
from ..unit import Unit
from .. import utils

class Taxi(Unit):
    def __init__(self, vehicle_id:tuple, city:City, init_status):
        super().__init__(vehicle_id, city, init_status, location_rng=city.vehicle_rng)
        self.status_table = {0:"assigned", 1:"in_service", 2:"idle", 3:"interchanged"}
        # around 30 mph
        self.speed = city.max_v
        self.load = 0
        # self.status = 2
        self.passenger = []
        # ordered list of passed nodes [..., cityNode1, cityNode2, cityNode3, ...]
        self.path1, self.path2 = [], []
        # determine whether the pre-assigned route is finished "real-world"
        self.start1 = True
        # distance of assigned, distance of service
        self.dist_a, self.dist_s, self.dist_idle = 0, 0, 0
        # assigned time and inservice time
        self.ta, self.ts, self.ti = 0, 0, 0
        # frequency of being called
        self.freq = 0

    def changeCity(self, city:City):
        self.city = city
        self.speed = city.max_v

    def avgti(self):
        return self.ti/(self.freq+1)

    def add(self, passenger:Passenger):
        passenger.vehicle = self.id
        if self.city.type_name == "Euclidean" or self.city.type_name == "Manhattan":
            # path info is stored as tuple ((x, y), position_type)
            # position_type 1 means passenger origin, 2 means passenger destination
            if len(self.passenger) == 0:
                self.path1 = [((passenger.x, passenger.y), 1)]
                self.path2 = [((passenger.dx, passenger.dy), 2)]
            else:
                self.path2.insert(0, ((passenger.dx, passenger.dy), 2))
                self.path2.insert(0, ((passenger.x, passenger.y), 1))

        elif self.city.type_name == "real-world":
            dist1, path1 = self.city.dijkstra(self.link.origin.id, passenger.link.origin.id)
            dist2, path2 = self.city.dijkstra(passenger.link.origin.id, passenger.d_link.origin.id)
            if (dist1 == -1 or dist2 == -1):
                return False
            # assign current location to passenger and passenger origin to destination
            self.path1 = path1
            self.path2 = path2
            self.start1 = True
        self.load += 1
        self.passenger.insert(0, passenger)

    def pick_up(self):
        self.passenger[0].status = 2
        self.passenger[0].t_s = self.clock
        onboard = [p for p in self.passenger if p.status == 2]
        if len(onboard) > 1:
            for p in onboard:
                p.ever_shared = True

    def release(self):
        if self.path2[0][1] == 2:
            self.passenger[0].status = 3
            self.passenger[0].t_end = self.clock
            self.passenger.pop(0)
            self.load -= 1
        self.path2.pop(0)

    def assign(self, passenger:Passenger):
        passenger.t_a = self.clock
        self.add(passenger)
        passenger.status = 1
        self.freq += 1
        status_request = self.changeStatusTo(0)
        return status_request

    def in_service(self):
        self.pick_up()
        status_request = self.changeStatusTo(1)
        return status_request

    def idle(self):
        self.passenger[0].status = 3
        self.passenger[0].t_end = self.clock
        self.passenger.pop(0)
        self.load -= 1
        self.path1, self.path2 = [], []
        self.idle_position = (self.x, self.y)
        status_request = self.changeStatusTo(2)
        return status_request

    def interchanging(self):
        status_requst = self.changeStatusTo(3)
        return status_requst

    def interchanged(self):
        status_request = self.changeStatusTo(2)
        return status_request

    # swap with other vehicle
    def swap(self, veh):
        temp1, temp2, temp3, temp4, temp5 = self.passenger, self.path1, self.path2, self.start1, self.load
        self.passenger, self.path1, self.path2, self.start1, self.load = veh.passenger, veh.path1, veh.path2, veh.start1, veh.load
        veh.passenger, veh.path1, veh.path2, veh.start1, veh.load = temp1, temp2, temp3, temp4, temp5
        for p in self.passenger:
            p.vehicle = self.id
        for p in veh.passenger:
            p.vehicle = veh.id
        status1, status2 = self.status, veh.status
        request1, request2 = self.changeStatusTo(status2), veh.changeStatusTo(status1)
        return (request1, request2)

    def idle_pos(self):
        x, y = 0, 0
        x = self.even_space*round(self.x / self.even_space)
        y = self.even_space*round(self.y / self.even_space)
        if x == 0:
            x += self.even_space
        elif x == self.city.length:
            x -= self.even_space
        if y == 0:
            y += self.even_space
        elif y == self.city.length:
            y -= self.even_space
        return (x, y)

    def location(self):
        if self.city.type_name == "Euclidean" or self.city.type_name == "Manhattan":
            return (self.x, self.y)

        if self.city.type_name == "real-world":
            (x, y) = utils.location_helper(self.link, self.len)
            return (x, y)

    # move along the path and update the location of vehicle
    def move(self, dt):
        self.clock += dt
        old_status = self.status
        before = (self.x, self.y)
        if old_status == 0:
            self.ta += dt
        elif old_status == 1:
            self.ts += dt
        elif old_status == 2:
            self.ti += dt
        request = (self.id, old_status, old_status)
        mover = self.move_Manhattan if self.city.type_name == "Manhattan" else self.move_Euclidean
        if old_status == 0:
            if mover(dt, self.path1[0][0]):
                request = self.in_service()
        elif old_status == 1:
            if mover(dt, self.path2[0][0]):
                if len(self.passenger) == 1:
                    request = self.idle()
                else:
                    if self.path2[0][1] == 1:
                        self.pick_up()
                    self.release()
        elif old_status in (2, 3):
            if mover(dt, self.idle_position) and old_status == 3:
                request = self.interchanged()
        dx, dy = self.x-before[0], self.y-before[1]
        distance = abs(dx)+abs(dy) if self.city.type_name == "Manhattan" else (dx*dx+dy*dy)**0.5
        if old_status == 0:
            self.dist_a += distance
        elif old_status == 1:
            self.dist_s += distance
        else:
            self.dist_idle += distance
        return request
