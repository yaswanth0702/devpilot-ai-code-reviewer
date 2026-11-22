"""Seeded-bug benchmark.

Each case is a small, realistic change with a known defect planted in it (or no defect, for the
"clean" cases that measure false positives). `expected` lines refer to the AFTER file.
A predicted comment matches when it's on the same file within +/-2 lines.
"""

CASES = [
    # ---------------------------------------------------------------- Java
    {
        "id": "java-sql-injection",
        "path": "src/main/java/app/UserDao.java",
        "before": """package app;

import java.sql.*;

public class UserDao {
    private final Connection conn;

    public UserDao(Connection conn) { this.conn = conn; }

    public ResultSet all() throws SQLException {
        return conn.createStatement().executeQuery("SELECT * FROM users");
    }
}
""",
        "after": """package app;

import java.sql.*;

public class UserDao {
    private final Connection conn;

    public UserDao(Connection conn) { this.conn = conn; }

    public ResultSet all() throws SQLException {
        return conn.createStatement().executeQuery("SELECT * FROM users");
    }

    public ResultSet byEmail(String email) throws SQLException {
        String sql = "SELECT * FROM users WHERE email = '" + email + "'";
        return conn.createStatement().executeQuery(sql);
    }
}
""",
        "expected": [{"line": 15, "category": "security"}],
    },
    {
        "id": "java-string-equality",
        "path": "src/main/java/app/RoleCheck.java",
        "before": """package app;

public class RoleCheck {
    public boolean canDelete(User u) {
        return false;
    }
}
""",
        "after": """package app;

public class RoleCheck {
    public boolean canDelete(User u) {
        if (u.getRole() == "ADMIN") {
            return true;
        }
        return false;
    }
}
""",
        "expected": [{"line": 5, "category": "bug"}],
    },
    {
        "id": "java-resource-leak",
        "path": "src/main/java/app/ReportReader.java",
        "before": """package app;

import java.io.*;

public class ReportReader {
}
""",
        "after": """package app;

import java.io.*;

public class ReportReader {
    public String firstLine(String path) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(path));
        String line = reader.readLine();
        if (line == null) {
            throw new IOException("empty report: " + path);
        }
        reader.close();
        return line;
    }
}
""",
        "expected": [{"line": 7, "category": "error_handling"}],
    },
    {
        "id": "java-race-condition",
        "path": "src/main/java/app/RequestCounter.java",
        "before": """package app;

import org.springframework.stereotype.Component;

@Component
public class RequestCounter {
}
""",
        "after": """package app;

import org.springframework.stereotype.Component;

@Component
public class RequestCounter {
    private int count = 0;

    // called from every request thread
    public int increment() {
        count++;
        return count;
    }
}
""",
        "expected": [{"line": 11, "category": "concurrency"}],
    },
    {
        "id": "java-optional-get",
        "path": "src/main/java/app/OrderService.java",
        "before": """package app;

public class OrderService {
    private final OrderRepository repo;

    public OrderService(OrderRepository repo) { this.repo = repo; }
}
""",
        "after": """package app;

public class OrderService {
    private final OrderRepository repo;

    public OrderService(OrderRepository repo) { this.repo = repo; }

    public double total(long orderId) {
        Order order = repo.findById(orderId).get();
        return order.getItems().stream().mapToDouble(Item::getPrice).sum();
    }
}
""",
        "expected": [{"line": 9, "category": "error_handling"}],
    },
    {
        "id": "java-swallowed-exception",
        "path": "src/main/java/app/PaymentClient.java",
        "before": """package app;

public class PaymentClient {
    private final Gateway gateway;

    public PaymentClient(Gateway gateway) { this.gateway = gateway; }
}
""",
        "after": """package app;

public class PaymentClient {
    private final Gateway gateway;

    public PaymentClient(Gateway gateway) { this.gateway = gateway; }

    public boolean charge(String customerId, long cents) {
        try {
            gateway.charge(customerId, cents);
        } catch (Exception e) {}
        return true;
    }
}
""",
        "expected": [{"line": 11, "category": "error_handling"}],
    },
    {
        "id": "java-off-by-one",
        "path": "src/main/java/app/Paginator.java",
        "before": """package app;

import java.util.*;

public class Paginator {
}
""",
        "after": """package app;

import java.util.*;

public class Paginator {
    public static <T> List<T> page(List<T> items, int page, int size) {
        List<T> out = new ArrayList<>();
        for (int i = page * size; i <= page * size + size; i++) {
            out.add(items.get(i));
        }
        return out;
    }
}
""",
        "expected": [{"line": 8, "category": "bug"}],
    },
    # ---------------------------------------------------------------- Python
    {
        "id": "py-hardcoded-secret",
        "path": "app/config.py",
        "before": """import os

DEBUG = os.getenv("DEBUG", "0") == "1"
""",
        "after": """import os

DEBUG = os.getenv("DEBUG", "0") == "1"
STRIPE_API_KEY = "fake-stripe-key-for-eval-0000000000"
""",
        "expected": [{"line": 4, "category": "security"}],
    },
    {
        "id": "py-mutable-default",
        "path": "app/cart.py",
        "before": """class Cart:
    pass
""",
        "after": """class Cart:
    pass


def add_item(item, items=[]):
    items.append(item)
    return items
""",
        "expected": [{"line": 5, "category": "bug"}],
    },
    {
        "id": "py-bare-except",
        "path": "app/sync.py",
        "before": """import requests


def fetch(url):
    return requests.get(url, timeout=10).json()
""",
        "after": """import requests


def fetch(url):
    try:
        return requests.get(url, timeout=10).json()
    except:
        pass
""",
        "expected": [{"line": 7, "category": "error_handling"}],
    },
    {
        "id": "py-n-plus-one",
        "path": "app/reports.py",
        "before": """from .db import session
from .models import Order, Customer
""",
        "after": """from .db import session
from .models import Order, Customer


def revenue_by_customer():
    totals = {}
    for customer in session.query(Customer).all():
        orders = session.query(Order).filter(Order.customer_id == customer.id).all()
        totals[customer.name] = sum(o.amount for o in orders)
    return totals
""",
        "expected": [{"line": 8, "category": "performance"}],
    },
    # ---------------------------------------------------------------- clean (no defects)
    {
        "id": "clean-java-refactor",
        "path": "src/main/java/app/PriceFormatter.java",
        "before": """package app;

public class PriceFormatter {
    public String format(long cents) {
        return "$" + (cents / 100) + "." + String.format("%02d", cents % 100);
    }
}
""",
        "after": """package app;

import java.math.BigDecimal;
import java.text.NumberFormat;
import java.util.Locale;

public class PriceFormatter {
    private static final NumberFormat USD = NumberFormat.getCurrencyInstance(Locale.US);

    public String format(long cents) {
        synchronized (USD) {
            return USD.format(BigDecimal.valueOf(cents, 2));
        }
    }
}
""",
        "expected": [],
    },
    {
        "id": "clean-py-param-query",
        "path": "app/users.py",
        "before": """def get_user(conn, user_id):
    return None
""",
        "after": """def get_user(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT id, email FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()
""",
        "expected": [],
    },
    {
        "id": "clean-java-try-with-resources",
        "path": "src/main/java/app/FileStats.java",
        "before": """package app;

public class FileStats {
}
""",
        "after": """package app;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;

public class FileStats {
    public static long countLines(Path path) throws IOException {
        try (Stream<String> lines = Files.lines(path)) {
            return lines.count();
        }
    }
}
""",
        "expected": [],
    },
]
