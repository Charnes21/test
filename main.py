import sys
import psycopg2
import osmnx as ox
import networkx as nx
import folium
from geopy.geocoders import Nominatim
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QLineEdit
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl
import os
import numpy as np
from scipy.interpolate import splprep, splev


class MapWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Интерактивная карта с маршрутом")
        self.setGeometry(100, 100, 800, 600)

        # Создание элементов интерфейса
        self.map_view = QWebEngineView()
        self.start_input = QLineEdit(self, placeholderText="Введите начальный адрес")
        self.end_input = QLineEdit(self, placeholderText="Введите конечный адрес")
        self.find_route_button = QPushButton("Найти маршрут", self)
        self.info_label = QLabel("Введите адреса и нажмите 'Найти маршрут'", self)

        # Настройка интерфейса
        layout = QVBoxLayout()
        layout.addWidget(self.start_input)
        layout.addWidget(self.end_input)
        layout.addWidget(self.find_route_button)
        layout.addWidget(self.info_label)

        # Устанавливаем размер карты на 3/4 окна
        self.map_view.setFixedHeight(self.height() * 3 // 4)
        layout.addWidget(self.map_view)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # Подключение сигнала кнопки
        self.find_route_button.clicked.connect(self.find_route)

    def resizeEvent(self, event):
        """Обновление размера карты при изменении размера окна."""
        super().resizeEvent(event)
        self.map_view.setFixedHeight(self.height() * 3 // 4)

    def connect_db(self):
        """Подключение к базе данных PostgreSQL."""
        return psycopg2.connect(
            dbname="test1",
            user="char",
            password="2103",
            host="localhost",
            port="5432"
        )

    def adjust_weights(self, G):
        """Изменение весов графа на основе данных из базы данных."""
        try:
            with self.connect_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT start_address, end_address FROM rout1")
                    routes = cursor.fetchall()

                    for start_address, end_address in routes:
                        start_coords = self.geocode_address(start_address)
                        end_coords = self.geocode_address(end_address)

                        if start_coords and end_coords:
                            start_node = ox.distance.nearest_nodes(G, X=start_coords[1], Y=start_coords[0])
                            end_node = ox.distance.nearest_nodes(G, X=end_coords[1], Y=end_coords[0])

                            if G.has_edge(start_node, end_node):
                                edge_data = G[start_node][end_node][0]
                                edge_data['custom_weight'] = edge_data.get('length', 1) + 10

                    cursor.execute("SELECT street_name, city, severity FROM traffic_incidents")
                    incidents = cursor.fetchall()

                    for street_name, city, severity in incidents:
                        location = self.geocode_address(f"{street_name}, {city}")
                        if location:
                            node = ox.distance.nearest_nodes(G, X=location[1], Y=location[0])
                            for neighbor in G.neighbors(node):
                                if G.has_edge(node, neighbor):
                                    edge_data = G[node][neighbor][0]
                                    edge_data['custom_weight'] = edge_data.get('length', 1) + severity

        except Exception as e:
            print(f"Ошибка при изменении весов графа: {e}")

    def geocode_address(self, address):
        """Геокодирование адреса в координаты."""
        geolocator = Nominatim(user_agent="route_planner")
        location = geolocator.geocode(address)
        return (location.latitude, location.longitude) if location else None

    def smooth_route(self, route_coords, smoothing_factor=0.01):
        """
        Сглаживает маршрут с использованием сплайнов.

        :param route_coords: Список кортежей координат [(lat1, lon1), (lat2, lon2), ...]
        :param smoothing_factor: Коэффициент сглаживания
        :return: Список сглаженных координат [(lat1, lon1), (lat2, lon2), ...]
        """
        lats, lons = zip(*route_coords)
        tck, u = splprep([lats, lons], s=smoothing_factor)
        unew = np.linspace(0, 1, len(lats) * 10)  # Увеличиваем число точек
        smooth_lats, smooth_lons = splev(unew, tck)
        return list(zip(smooth_lats, smooth_lons))

    def find_route(self):
        start_address = self.start_input.text()
        end_address = self.end_input.text()

        start_point = self.geocode_address(start_address)
        end_point = self.geocode_address(end_address)

        if start_point and end_point:
            city_name = "Krasnodar, Russia"
            G = ox.graph_from_place(city_name, network_type='drive')
            self.adjust_weights(G)

            try:
                start_node = ox.distance.nearest_nodes(G, X=start_point[1], Y=start_point[0])
                end_node = ox.distance.nearest_nodes(G, X=end_point[1], Y=end_point[0])

                # Оптимальный маршрут
                optimal_route = nx.shortest_path(G, start_node, end_node, weight='custom_weight')

                # Кратчайший маршрут
                shortest_route = nx.shortest_path(G, start_node, end_node, weight='length')

                # Альтернативный маршрут (второй лучший)
                alternative_route = None
                all_routes = list(nx.shortest_simple_paths(G, start_node, end_node, weight='custom_weight'))
                if len(all_routes) > 1:
                    alternative_route = all_routes[1]

                # Создание карты
                route_map = folium.Map(location=start_point, zoom_start=14)

                if optimal_route:
                    optimal_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in optimal_route]
                    smooth_optimal_coords = self.smooth_route(optimal_coords)
                    folium.PolyLine(smooth_optimal_coords, color="blue", weight=5, opacity=0.8,
                                    tooltip="Оптимальный маршрут").add_to(route_map)

                if shortest_route:
                    shortest_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in shortest_route]
                    smooth_shortest_coords = self.smooth_route(shortest_coords)
                    folium.PolyLine(smooth_shortest_coords, color="green", weight=3, opacity=0.6,
                                    tooltip="Кратчайший маршрут").add_to(route_map)

                if alternative_route:
                    alternative_coords = [(G.nodes[node]['y'], G.nodes[node]['x']) for node in alternative_route]
                    smooth_alternative_coords = self.smooth_route(alternative_coords)
                    folium.PolyLine(smooth_alternative_coords, color="orange", weight=4, opacity=0.7,
                                    tooltip="Альтернативный маршрут").add_to(route_map)

                project_dir = os.path.dirname(os.path.abspath(__file__))
                map_file_path = os.path.join(project_dir, "route_map.html")
                route_map.save(map_file_path)
                self.map_view.setUrl(QUrl.fromLocalFile(map_file_path))
                self.info_label.setText("Маршрут найден и показан!")

            except nx.NetworkXNoPath:
                self.info_label.setText("Нет доступного маршрута.")

        else:
            self.info_label.setText("Ошибка при поиске маршрута.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MapWindow()
    window.show()
    sys.exit(app.exec_())
