#include <cmath>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::vector<double> parse_values(const std::string& line, std::size_t expected, const char* label) {
    std::istringstream in(line);
    std::vector<double> values;
    double value = 0.0;
    while (in >> value) {
        if (!std::isfinite(value)) {
            throw std::runtime_error(std::string(label) + " contains non-finite value");
        }
        values.push_back(value);
    }
    if (values.size() != expected) {
        throw std::runtime_error(
            std::string(label) + " expected " + std::to_string(expected) +
            " values, got " + std::to_string(values.size())
        );
    }
    return values;
}

struct FrozenRidge {
    std::vector<double> mean;
    std::vector<double> scale;
    std::vector<double> coef;

    double predict(const std::vector<double>& x) const {
        if (x.size() != mean.size()) {
            throw std::runtime_error("feature row has wrong width");
        }
        double out = coef[0];
        for (std::size_t j = 0; j < x.size(); ++j) {
            if (!std::isfinite(x[j])) {
                throw std::runtime_error("feature row contains non-finite value");
            }
            out += ((x[j] - mean[j]) / scale[j]) * coef[j + 1];
        }
        return out;
    }
};

FrozenRidge load_model(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("cannot open model file: " + path);
    }

    std::string line;
    if (!std::getline(in, line)) {
        throw std::runtime_error("model file missing feature count");
    }
    std::istringstream count_stream(line);
    std::size_t n = 0;
    if (!(count_stream >> n) || n == 0) {
        throw std::runtime_error("invalid feature count");
    }

    std::string mean_line;
    std::string scale_line;
    std::string coef_line;
    if (!std::getline(in, mean_line) || !std::getline(in, scale_line) || !std::getline(in, coef_line)) {
        throw std::runtime_error("model file is incomplete");
    }

    FrozenRidge model{
        parse_values(mean_line, n, "mean"),
        parse_values(scale_line, n, "scale"),
        parse_values(coef_line, n + 1, "coef"),
    };
    for (double scale : model.scale) {
        if (!(scale > 0.0)) {
            throw std::runtime_error("scale must be positive");
        }
    }
    return model;
}

std::vector<double> parse_feature_row(const std::string& line, std::size_t expected) {
    std::string normalised = line;
    for (char& ch : normalised) {
        if (ch == ',') {
            ch = ' ';
        }
    }
    return parse_values(normalised, expected, "feature row");
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc != 2) {
            std::cerr << "usage: frozen_ridge_infer MODEL.txt < FEATURES.csv\n";
            return 2;
        }
        const FrozenRidge model = load_model(argv[1]);
        std::cout << std::setprecision(17);

        std::string line;
        std::size_t row = 0;
        while (std::getline(std::cin, line)) {
            if (line.empty()) {
                continue;
            }
            ++row;
            try {
                const auto x = parse_feature_row(line, model.mean.size());
                std::cout << model.predict(x) << '\n';
            } catch (const std::exception& exc) {
                throw std::runtime_error("input row " + std::to_string(row) + ": " + exc.what());
            }
        }
        return 0;
    } catch (const std::exception& exc) {
        std::cerr << "frozen_ridge_infer: " << exc.what() << '\n';
        return 1;
    }
}
